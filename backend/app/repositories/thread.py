"""
Repositories for Thread and ThreadMessage.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.thread import Thread, ThreadMessage

from .base import BaseRepository


class ThreadRepository(BaseRepository[Thread]):
    def __init__(self, db: AsyncSession):
        super().__init__(Thread, db)

    async def list_by_agent(self, agent_id: uuid.UUID) -> List[Thread]:
        query = (
            select(Thread)
            .where(Thread.agent_id == agent_id)
            .order_by(Thread.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[Thread]:
        query = (
            select(Thread)
            .where(Thread.workspace_id == workspace_id)
            .order_by(Thread.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_messages(self, thread_id: uuid.UUID) -> Optional[Thread]:
        query = (
            select(Thread)
            .where(Thread.id == thread_id)
            .options(selectinload(Thread.messages))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class ThreadMessageRepository(BaseRepository[ThreadMessage]):
    def __init__(self, db: AsyncSession):
        super().__init__(ThreadMessage, db)

    async def list_by_thread(self, thread_id: uuid.UUID) -> List[ThreadMessage]:
        query = (
            select(ThreadMessage)
            .where(ThreadMessage.thread_id == thread_id)
            .order_by(ThreadMessage.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
