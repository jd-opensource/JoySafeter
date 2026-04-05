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
        """List all tools owned by the user."""
        result = await self.db.execute(select(CustomTool).where(CustomTool.owner_id == user_id))
        return list(result.scalars().all())

    async def count_by_user(self, user_id: str) -> int:
        """Count tools owned by the user."""
        result = await self.db.execute(select(CustomTool).where(CustomTool.owner_id == user_id))
        return len(list(result.scalars().all()))

    async def delete_by_id(self, tool_id: uuid.UUID) -> int:
        """Delete a tool by ID."""
        stmt = delete(CustomTool).where(CustomTool.id == tool_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
