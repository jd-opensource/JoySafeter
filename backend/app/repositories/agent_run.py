"""
Repository for AgentRun.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRelease, AgentVersion
from app.models.agent_run import AgentRun

from .base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentRun, db)

    async def list_by_workspace(self, workspace_id: uuid.UUID, limit: int = 50) -> List[AgentRun]:
        """List all runs for a workspace."""
        query = (
            select(AgentRun)
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_release(
        self,
        release_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> List[AgentRun]:
        """List all runs for a specific release."""
        query = select(AgentRun).where(AgentRun.release_id == release_id).order_by(AgentRun.created_at.desc())
        if workspace_id:
            query = query.where(AgentRun.workspace_id == workspace_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_task(
        self,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> List[AgentRun]:
        """List all runs for a specific task."""
        query = select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at.desc())
        if workspace_id:
            query = query.where(AgentRun.workspace_id == workspace_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_by_agent_and_trigger(
        self,
        agent_id: uuid.UUID,
        workspace_id: uuid.UUID,
        trigger_medium: Optional[str] = None,
        run_purpose: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AgentRun]:
        """Find runs for a specific agent, optionally filtered by trigger_medium, run_purpose and status."""
        query = (
            select(AgentRun)
            .outerjoin(AgentRelease, AgentRun.release_id == AgentRelease.id)
            .outerjoin(
                AgentVersion,
                or_(
                    AgentRelease.agent_version_id == AgentVersion.id,
                    AgentRun.agent_version_id == AgentVersion.id,
                ),
            )
            .where(AgentVersion.agent_id == agent_id)
            .where(AgentRun.workspace_id == workspace_id)
        )
        if trigger_medium:
            query = query.where(AgentRun.trigger_medium == trigger_medium)
        if run_purpose:
            query = query.where(AgentRun.run_purpose == run_purpose)
        if status:
            query = query.where(AgentRun.status == status)
        query = query.order_by(AgentRun.created_at.desc()).limit(10)
        result = await self.db.execute(query)
        return list(result.scalars().all())
