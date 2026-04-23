"""
AgentReleaseService — manages AgentRelease lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
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
            raise NotFoundException(f"AgentRelease {release_id} not found")
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
            raise NotFoundException(f"AgentVersion {data.agent_version_id} not found")
        if version.agent_id != agent_id:
            raise BadRequestException("Version does not belong to this agent")
        if version.status != "frozen":
            raise BadRequestException("Version must be frozen before publishing a release")

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

        await self.commit()
        logger.info(
            f"Published release {release.id} (r{next_num}) for agent {agent_id}"
        )
        return release

    async def activate_release(
        self, agent_id: uuid.UUID, release_id: uuid.UUID
    ) -> AgentRelease:
        release = await self.release_repo.get(release_id)
        if not release:
            raise NotFoundException(f"AgentRelease {release_id} not found")
        if release.status != "ready":
            raise BadRequestException("Only releases with status 'ready' can be activated")

        # Set agent.active_release_id
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        update_data: dict = {"active_release_id": release_id}
        if agent.status != "active":
            AGENT_SM.validate(agent.status, "active")
            update_data["status"] = "active"

        await self.agent_repo.update(agent_id, update_data)
        await self.commit()
        logger.info(f"Activated release {release_id} for agent {agent_id}")
        return release

    async def retire_release(
        self, agent_id: uuid.UUID, release_id: uuid.UUID
    ) -> AgentRelease:
        release = await self.release_repo.get(release_id)
        if not release:
            raise NotFoundException(f"AgentRelease {release_id} not found")

        RELEASE_SM.validate(release.status, "retired")
        updated = await self.release_repo.update(
            release_id, {"status": "retired", "retired_at": utc_now()}
        )
        assert updated is not None

        # If this was the active release, clear it
        agent = await self.agent_repo.get(agent_id)
        if agent and agent.active_release_id == release_id:
            await self.agent_repo.update(agent_id, {"active_release_id": None})

        await self.commit()
        logger.info(f"Retired release {release_id} for agent {agent_id}")
        return updated
