"""
GraphExecution Repository
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph_execution import GraphExecution

from .base import BaseRepository


class GraphExecutionRepository(BaseRepository[GraphExecution]):
    def __init__(self, db: AsyncSession):
        super().__init__(GraphExecution, db)

    async def get_by_id_and_user(self, execution_id: uuid.UUID, user_id: str) -> Optional[GraphExecution]:
        """获取指定用户的执行记录"""
        result = await self.db.execute(
            select(GraphExecution).where(
                GraphExecution.id == execution_id,
                GraphExecution.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
