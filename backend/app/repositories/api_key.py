"""
ApiKey Repository
"""

from __future__ import annotations

import uuid
from typing import List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey

from .base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    def __init__(self, db: AsyncSession):
        super().__init__(ApiKey, db)

    async def list_by_user(self, user_id: uuid.UUID) -> List[ApiKey]:
        result = await self.db.execute(select(ApiKey).where(ApiKey.user_id == user_id))
        return list(result.scalars().all())

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[ApiKey]:
        result = await self.db.execute(select(ApiKey).where(ApiKey.workspace_id == workspace_id))
        return list(result.scalars().all())

    async def delete_by_id(self, key_id: uuid.UUID) -> int:
        stmt = delete(ApiKey).where(ApiKey.id == key_id)
        result = await self.db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
