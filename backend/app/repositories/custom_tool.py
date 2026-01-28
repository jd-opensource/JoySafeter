"""
CustomTool Repository
"""

from __future__ import annotations

import uuid
from typing import List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_tool import CustomTool

from .base import BaseRepository


class CustomToolRepository(BaseRepository[CustomTool]):
    def __init__(self, db: AsyncSession):
        super().__init__(CustomTool, db)

    async def list_by_user(self, user_id: str) -> List[CustomTool]:
        """获取用户的所有工具"""
        result = await self.db.execute(select(CustomTool).where(CustomTool.owner_id == user_id))
        return list(result.scalars().all())

    async def count_by_user(self, user_id: str) -> int:
        """统计用户拥有的工具数量"""
        result = await self.db.execute(select(CustomTool).where(CustomTool.owner_id == user_id))
        return len(list(result.scalars().all()))

    async def delete_by_id(self, tool_id: uuid.UUID) -> int:
        """根据 ID 删除工具"""
        stmt = delete(CustomTool).where(CustomTool.id == tool_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
