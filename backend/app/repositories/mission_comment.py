"""
MissionComment repository helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import asc, desc, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission_comment import CommentAuthorType, MissionComment

from .base import BaseRepository


class MissionCommentRepository(BaseRepository[MissionComment]):
    def __init__(self, db: AsyncSession):
        super().__init__(MissionComment, db)

    async def list_by_mission(
        self,
        mission_id: uuid.UUID,
        *,
        cursor: Optional[datetime] = None,
        limit: int = 50,
        order_asc: bool = True,
    ) -> Sequence[MissionComment]:
        query = select(MissionComment).where(MissionComment.mission_id == mission_id)
        if cursor is not None:
            if order_asc:
                query = query.where(MissionComment.created_at > cursor)
            else:
                query = query.where(MissionComment.created_at < cursor)
        order = asc(MissionComment.created_at) if order_asc else desc(MissionComment.created_at)
        result = await self.db.execute(query.order_by(order).limit(limit))
        return result.scalars().all()

    async def get_by_id_and_mission(self, comment_id: uuid.UUID, mission_id: uuid.UUID) -> Optional[MissionComment]:
        result = await self.db.execute(
            select(MissionComment).where(
                MissionComment.id == comment_id,
                MissionComment.mission_id == mission_id,
            )
        )
        return result.scalar_one_or_none()

    async def has_agent_commented_since(
        self,
        mission_id: uuid.UUID,
        agent_id: str,
        since: datetime,
    ) -> bool:
        stmt = (
            select(literal(True))
            .where(
                MissionComment.mission_id == mission_id,
                MissionComment.author_type == CommentAuthorType.AGENT,
                MissionComment.author_id == agent_id,
                MissionComment.created_at >= since,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar() is not None
