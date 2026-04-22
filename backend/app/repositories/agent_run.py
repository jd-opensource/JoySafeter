"""
Repository for AgentRun.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun

from .base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentRun, db)

    async def list_by_workspace(
        self, workspace_id: uuid.UUID, limit: int = 50
    ) -> List[AgentRun]:
        """List all runs for a workspace."""
        query = (
            select(AgentRun)
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_release(self, release_id: uuid.UUID) -> List[AgentRun]:
        """List all runs for a specific release."""
        query = (
            select(AgentRun)
            .where(AgentRun.release_id == release_id)
            .order_by(AgentRun.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_task(self, task_id: uuid.UUID) -> List[AgentRun]:
        """List all runs for a specific task."""
        query = (
            select(AgentRun)
            .where(AgentRun.task_id == task_id)
            .order_by(AgentRun.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
