"""
TaskComment repository helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import asc, desc, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_comment import CommentAuthorType, TaskComment

from .base import BaseRepository


class TaskCommentRepository(BaseRepository[TaskComment]):
    def __init__(self, db: AsyncSession):
        super().__init__(TaskComment, db)

    async def list_by_task(
        self,
        task_id: uuid.UUID,
        *,
        cursor: Optional[datetime] = None,
        limit: int = 50,
        order_asc: bool = True,
    ) -> Sequence[TaskComment]:
        query = select(TaskComment).where(TaskComment.task_id == task_id)
        if cursor is not None:
            if order_asc:
                query = query.where(TaskComment.created_at > cursor)
            else:
                query = query.where(TaskComment.created_at < cursor)
        order = asc(TaskComment.created_at) if order_asc else desc(TaskComment.created_at)
        result = await self.db.execute(query.order_by(order).limit(limit))
        return result.scalars().all()

    async def get_by_id_and_task(self, comment_id: uuid.UUID, task_id: uuid.UUID) -> Optional[TaskComment]:
        result = await self.db.execute(
            select(TaskComment).where(
                TaskComment.id == comment_id,
                TaskComment.task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def has_agent_commented_since(
        self,
        task_id: uuid.UUID,
        agent_id: str,
        since: datetime,
    ) -> bool:
        stmt = (
            select(literal(True))
            .where(
                TaskComment.task_id == task_id,
                TaskComment.author_type == CommentAuthorType.AGENT,
                TaskComment.author_id == agent_id,
                TaskComment.created_at >= since,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar() is not None
