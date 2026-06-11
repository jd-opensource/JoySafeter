"""
TaskActivity repository helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import asc, desc, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.task_activity import ActivityAuthorType, TaskActivity

from .base import BaseRepository


class TaskActivityRepository(BaseRepository[TaskActivity]):
    def __init__(self, db: AsyncSession):
        super().__init__(TaskActivity, db)

    async def list_by_task(
        self,
        task_id: uuid.UUID,
        *,
        cursor: Optional[datetime] = None,
        limit: int = 50,
        order_asc: bool = True,
    ) -> Sequence[TaskActivity]:
        query = select(TaskActivity).where(TaskActivity.task_id == task_id)
        if cursor is not None:
            if order_asc:
                query = query.where(TaskActivity.created_at > cursor)
            else:
                query = query.where(TaskActivity.created_at < cursor)
        order = asc(TaskActivity.created_at) if order_asc else desc(TaskActivity.created_at)
        result = await self.db.execute(query.order_by(order).limit(limit))
        return result.scalars().all()

    async def get_by_id_and_task(self, activity_id: uuid.UUID, task_id: uuid.UUID) -> Optional[TaskActivity]:
        result = await self.db.execute(
            select(TaskActivity).where(
                TaskActivity.id == activity_id,
                TaskActivity.task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def has_agent_posted_since(
        self,
        task_id: uuid.UUID,
        agent_id: str,
        since: datetime,
    ) -> bool:
        stmt = (
            select(literal(True))
            .where(
                TaskActivity.task_id == task_id,
                TaskActivity.author_type == ActivityAuthorType.AGENT,
                TaskActivity.author_id == agent_id,
                TaskActivity.created_at >= since,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar() is not None
