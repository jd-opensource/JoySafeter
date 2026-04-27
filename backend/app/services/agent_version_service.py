"""
AgentVersionService — manages AgentVersion lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.core.state_machines import VERSION_SM
from app.models.agent import AgentVersion
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent_version import CreateAgentVersionRequest, UpdateAgentVersionRequest


from .base import BaseService


class AgentVersionService(BaseService):
    """Manages AgentVersion entities."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.version_repo = AgentVersionRepository(db)
        self.agent_repo = AgentRepository(db)

    async def list_versions(self, agent_id: uuid.UUID) -> List[AgentVersion]:
        return await self.version_repo.list_by_agent(agent_id)

    async def get_version(self, version_id: uuid.UUID) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundError(
                "Agent version not found",
                code="AGENT_VERSION_NOT_FOUND",
                data={"version_id": str(version_id)},
            )
        return version

    async def create_version(
        self,
        agent_id: uuid.UUID,
        user_id: str,
        data: CreateAgentVersionRequest,
    ) -> AgentVersion:
        # Auto-increment version number
        max_num = await self.version_repo.get_max_version_number(agent_id)
        next_num = max_num + 1

        version = await self.version_repo.create(
            {
                "agent_id": agent_id,
                "version_number": next_num,
                "status": "draft",
                "source_kind": data.source_kind or "manual",
                "definition_kind": data.definition_kind,
                "definition_payload": data.definition_payload or {},
                "capability_manifest": data.capability_manifest or {},
                "changelog": data.changelog,
                "created_by": user_id,
            }
        )

        # Update agent's current_draft_version_id
        await self.agent_repo.update(agent_id, {"current_draft_version_id": version.id})

        await self.commit()
        logger.info(f"Created version {version.id} (v{next_num}) for agent {agent_id}")
        return version

    async def update_version(
        self,
        version_id: uuid.UUID,
        data: UpdateAgentVersionRequest,
    ) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundError(
                "Agent version not found",
                code="AGENT_VERSION_NOT_FOUND",
                data={"version_id": str(version_id)},
            )

        if version.status == "frozen":
            raise InvalidRequestError("Cannot update a frozen version", code="AGENT_VERSION_FROZEN")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return version

        updated = await self.version_repo.update(version_id, update_data)
        assert updated is not None
        await self.commit()
        return updated

    async def freeze_version(self, version_id: uuid.UUID) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundError(
                "Agent version not found",
                code="AGENT_VERSION_NOT_FOUND",
                data={"version_id": str(version_id)},
            )

        VERSION_SM.validate(version.status, "frozen")
        updated = await self.version_repo.update(version_id, {"status": "frozen"})
        assert updated is not None
        logger.info(f"Froze version {version_id}")
        return updated
