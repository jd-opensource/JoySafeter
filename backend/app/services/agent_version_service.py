"""
AgentVersionService — manages AgentVersion lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.state_machines import VERSION_SM
from app.models.agent import AgentVersion
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent_version import CreateAgentVersionRequest, UpdateAgentVersionRequest


class AgentVersionService:
    """Manages AgentVersion entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.version_repo = AgentVersionRepository(db)
        self.agent_repo = AgentRepository(db)

    async def list_versions(self, agent_id: uuid.UUID) -> List[AgentVersion]:
        return await self.version_repo.list_by_agent(agent_id)

    async def get_version(self, version_id: uuid.UUID) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundException(f"AgentVersion {version_id} not found")
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

        logger.info(f"Created version {version.id} (v{next_num}) for agent {agent_id}")
        return version

    async def update_version(
        self,
        version_id: uuid.UUID,
        data: UpdateAgentVersionRequest,
    ) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundException(f"AgentVersion {version_id} not found")

        if version.status == "frozen":
            raise BadRequestException("Cannot update a frozen version")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return version

        updated = await self.version_repo.update(version_id, update_data)
        assert updated is not None
        return updated

    async def freeze_version(self, version_id: uuid.UUID) -> AgentVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundException(f"AgentVersion {version_id} not found")

        VERSION_SM.validate(version.status, "frozen")
        updated = await self.version_repo.update(version_id, {"status": "frozen"})
        assert updated is not None
        logger.info(f"Froze version {version_id}")
        return updated

    async def unfreeze_version(self, version_id: uuid.UUID) -> AgentVersion:
        """Revert a frozen version back to draft status.

        Used for rollback when a freeze succeeds but the subsequent publish
        operation fails, to avoid leaving the version in an uneditable frozen
        state with no associated release.
        """
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundException(f"AgentVersion {version_id} not found")

        if version.status != "frozen":
            raise BadRequestException(
                f"Cannot unfreeze version with status '{version.status}'; only 'frozen' versions can be reverted to draft"
            )

        VERSION_SM.validate(version.status, "draft")
        updated = await self.version_repo.update(version_id, {"status": "draft"})
        assert updated is not None
        logger.info(f"Unfroze version {version_id} (reverted to draft)")
        return updated
