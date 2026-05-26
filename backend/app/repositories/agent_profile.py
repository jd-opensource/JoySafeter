"""
AgentProfile repository helpers.
"""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile, AgentStatus

from .base import BaseRepository


class AgentProfileRepository(BaseRepository[AgentProfile]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentProfile, db)

    async def get_by_id_and_workspace(self, profile_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[AgentProfile]:
        result = await self.db.execute(
            select(AgentProfile).where(
                AgentProfile.id == profile_id,
                AgentProfile.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        runtime_type: Optional[str] = None,
        limit: int = 100,
    ) -> Sequence[AgentProfile]:
        query = select(AgentProfile).where(AgentProfile.workspace_id == workspace_id)
        if status:
            query = query.where(AgentProfile.status == status)
        if runtime_type:
            query = query.where(AgentProfile.runtime_type == runtime_type)
        result = await self.db.execute(query.order_by(desc(AgentProfile.created_at)).limit(limit))
        return result.scalars().all()

    async def find_available(
        self, *, workspace_id: uuid.UUID, runtime_type: Optional[str] = None
    ) -> Sequence[AgentProfile]:
        """Find agents in IDLE status that can accept new tasks."""
        query = select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.status == AgentStatus.IDLE,
        )
        if runtime_type:
            query = query.where(AgentProfile.runtime_type == runtime_type)
        result = await self.db.execute(query.order_by(AgentProfile.created_at.asc()))
        return result.scalars().all()

    async def get_for_update(self, profile_id: uuid.UUID) -> Optional[AgentProfile]:
        result = await self.db.execute(select(AgentProfile).where(AgentProfile.id == profile_id).with_for_update())
        return result.scalar_one_or_none()
