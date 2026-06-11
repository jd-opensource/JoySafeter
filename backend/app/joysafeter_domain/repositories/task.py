"""
Task repository helpers.
"""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.task import Task, TaskStatus

from .base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    def __init__(self, db: AsyncSession):
        super().__init__(Task, db)

    async def get_by_id_and_workspace(self, task_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.project_id == str(workspace_id),
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, task_id: uuid.UUID, workspace_id: Optional[uuid.UUID] = None) -> Optional[Task]:
        query = select(Task).where(Task.id == task_id)
        if workspace_id is not None:
            query = query.where(Task.project_id == str(workspace_id))
        result = await self.db.execute(query.with_for_update())
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
        agent_id: Optional[uuid.UUID] = None,
        parent_task_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> Sequence[Task]:
        query = select(Task).where(Task.project_id == str(workspace_id))
        if status:
            query = query.where(Task.status == status)
        if creator_id:
            query = query.where(Task.creator_id == creator_id)
        if agent_id:
            query = query.where(Task.agent_id == agent_id)
        if parent_task_id:
            query = query.where(Task.parent_task_id == parent_task_id)
        result = await self.db.execute(query.order_by(Task.position.asc(), desc(Task.created_at)).limit(limit))
        return result.scalars().all()

    async def list_dispatchable(self, *, workspace_id: Optional[uuid.UUID] = None, limit: int = 10) -> Sequence[Task]:
        """Find BACKLOG tasks with an agent assigned, ready for dispatch.

        When workspace_id is None, searches across all projects.
        """
        query = select(Task).where(
            Task.status == TaskStatus.BACKLOG,
            Task.agent_id.isnot(None),
            Task.latest_run_id.is_(None),
        )
        if workspace_id is not None:
            query = query.where(Task.project_id == str(workspace_id))
        result = await self.db.execute(query.order_by(Task.position.asc(), Task.created_at.asc()).limit(limit))
        return result.scalars().all()
