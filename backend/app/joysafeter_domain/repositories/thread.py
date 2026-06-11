"""
Repositories for Thread.
"""

from __future__ import annotations

import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.thread import Thread

from .base import BaseRepository


class ThreadRepository(BaseRepository[Thread]):
    def __init__(self, db: AsyncSession):
        super().__init__(Thread, db)

    async def list_by_agent(self, agent_id: uuid.UUID) -> List[Thread]:
        query = select(Thread).where(Thread.agent_id == agent_id).order_by(Thread.updated_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_project(self, project_id: str) -> List[Thread]:
        query = select(Thread).where(Thread.project_id == project_id).order_by(Thread.updated_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())
