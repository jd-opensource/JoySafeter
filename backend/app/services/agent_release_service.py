"""
AgentReleaseService — manages AgentRelease lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.core.state_machines import AGENT_SM, RELEASE_SM
from app.models.agent import AgentRelease
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.repositories.agent_release import AgentReleaseRepository
from app.schemas.agent_release import CreateAgentReleaseRequest
from app.utils.datetime import utc_now


from .base import BaseService


class AgentReleaseService(BaseService):
    """Manages AgentRelease entities."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.release_repo = AgentReleaseRepository(db)
        self.version_repo = AgentVersionRepository(db)
        self.agent_repo = AgentRepository(db)

    async def list_releases(self, agent_id: uuid.UUID) -> List[AgentRelease]:
        return await self.release_repo.list_by_agent(agent_id)

    async def get_release(self, release_id: uuid.UUID) -> AgentRelease:
        release = await self.release_repo.get(release_id)
        if not release:
            raise NotFoundError(
                "Agent release not found",
                code="AGENT_RELEASE_NOT_FOUND",
                data={"release_id": str(release_id)},
            )
        return release

    async def publish_release(
        self,
        agent_id: uuid.UUID,
        user_id: str,
        data: CreateAgentReleaseRequest,
    ) -> AgentRelease:
        # Verify the version exists and belongs to this agent
        version = await self.version_repo.get(data.agent_version_id)
        if not version:
            raise NotFoundError(
                "Agent version not found",
                code="AGENT_VERSION_NOT_FOUND",
                data={"version_id": str(data.agent_version_id)},
            )
        if version.agent_id != agent_id:
            raise InvalidRequestError(
                "Version does not belong to this agent",
                code="AGENT_VERSION_AGENT_MISMATCH",
                data={"agent_id": str(agent_id), "version_id": str(data.agent_version_id)},
            )
        if version.status != "frozen":
            raise InvalidRequestError(
                "Version must be frozen before publishing a release",
                code="AGENT_VERSION_NOT_FROZEN",
                data={"version_id": str(data.agent_version_id), "status": version.status},
            )

        # Auto-increment release_number per agent_version_id
        max_num = await self.release_repo.get_max_release_number(data.agent_version_id)
        next_num = max_num + 1

        release = await self.release_repo.create(
            {
                "agent_version_id": data.agent_version_id,
                "release_number": next_num,
                "status": "ready",
                "runtime_kind": data.runtime_kind,
                "builder_kind": data.builder_kind,
                "runtime_binding": data.runtime_binding,
                "published_by": user_id,
                "published_at": utc_now(),
            }
        )

        logger.info(
            f"Published release {release.id} (r{next_num}) for agent {agent_id}"
        )
        return release

    async def activate_release(
        self, agent_id: uuid.UUID, release_id: uuid.UUID
    ) -> AgentRelease:
        release = await self.release_repo.get(release_id)
        if not release:
            raise NotFoundError(
                "Agent release not found",
                code="AGENT_RELEASE_NOT_FOUND",
                data={"release_id": str(release_id)},
            )
        if release.status != "ready":
            raise InvalidRequestError(
                "Only releases with status 'ready' can be activated",
                code="AGENT_RELEASE_NOT_READY",
                data={"release_id": str(release_id), "status": release.status},
            )

        # Set agent.active_release_id
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        update_data: dict = {"active_release_id": release_id}
        if agent.status != "active":
            AGENT_SM.validate(agent.status, "active")
            update_data["status"] = "active"

        await self.agent_repo.update(agent_id, update_data)
        logger.info(f"Activated release {release_id} for agent {agent_id}")
        return release

    async def retire_release(
        self, agent_id: uuid.UUID, release_id: uuid.UUID
    ) -> AgentRelease:
        release = await self.release_repo.get(release_id)
        if not release:
            raise NotFoundError(
                "Agent release not found",
                code="AGENT_RELEASE_NOT_FOUND",
                data={"release_id": str(release_id)},
            )

        RELEASE_SM.validate(release.status, "retired")
        updated = await self.release_repo.update(
            release_id, {"status": "retired", "retired_at": utc_now()}
        )
        assert updated is not None

        # If this was the active release, clear it and revert status
        agent = await self.agent_repo.get(agent_id)
        if agent and agent.active_release_id == release_id:
            update_data: dict = {"active_release_id": None}
            if agent.status == "active":
                AGENT_SM.validate(agent.status, "draft")
                update_data["status"] = "draft"
            await self.agent_repo.update(agent_id, update_data)

        logger.info(f"Retired release {release_id} for agent {agent_id}")
        return updated
