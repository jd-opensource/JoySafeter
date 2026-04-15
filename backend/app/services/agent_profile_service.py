"""
AgentProfile service layer.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile, AgentStatus
from app.repositories.agent_profile import AgentProfileRepository


class AgentProfileService:
    """Manages agent profile lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AgentProfileRepository(db)

    async def create_profile(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        runtime_type: str,
        description: Optional[str] = None,
        avatar: Optional[str] = None,
        instructions: Optional[str] = None,
        skill_ids: Optional[list] = None,
        custom_env: Optional[dict[str, Any]] = None,
        runtime_config: Optional[dict[str, Any]] = None,
        max_concurrent_tasks: int = 1,
    ) -> AgentProfile:
        profile = AgentProfile(
            workspace_id=workspace_id,
            name=name,
            runtime_type=runtime_type,
            description=description,
            avatar=avatar,
            instructions=instructions,
            skill_ids=skill_ids,
            custom_env=custom_env,
            runtime_config=runtime_config,
            max_concurrent_tasks=max_concurrent_tasks,
            status=AgentStatus.IDLE,
        )
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        logger.info(f"Created agent profile: {profile.id} ({name})")
        return profile

    async def get_profile(
        self, profile_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Optional[AgentProfile]:
        return await self.repo.get_by_id_and_workspace(profile_id, workspace_id)

    async def list_profiles(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        runtime_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[AgentProfile]:
        return list(
            await self.repo.list_by_workspace(
                workspace_id=workspace_id,
                status=status,
                runtime_type=runtime_type,
                limit=limit,
            )
        )

    async def update_status(
        self, profile_id: uuid.UUID, status: AgentStatus
    ) -> Optional[AgentProfile]:
        profile = await self.repo.get_for_update(profile_id)
        if not profile:
            return None
        profile.status = status
        await self.db.commit()
        return profile

    async def find_available_agents(
        self, *, workspace_id: uuid.UUID, runtime_type: Optional[str] = None
    ) -> list[AgentProfile]:
        return list(
            await self.repo.find_available(
                workspace_id=workspace_id, runtime_type=runtime_type
            )
        )

    async def update_profile(
        self,
        profile_id: uuid.UUID,
        workspace_id: uuid.UUID,
        **kwargs: Any,
    ) -> Optional[AgentProfile]:
        profile = await self.repo.get_by_id_and_workspace(profile_id, workspace_id)
        if not profile:
            return None
        allowed = {
            "name", "description", "avatar", "instructions",
            "skill_ids", "custom_env", "runtime_config",
            "max_concurrent_tasks", "runtime_type", "visibility",
        }
        for key, value in kwargs.items():
            if key in allowed:
                setattr(profile, key, value)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile
