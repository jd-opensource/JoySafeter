"""
ModelCredential Repository
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model_credential import ModelCredential

from .base import BaseRepository


class ModelCredentialRepository(BaseRepository[ModelCredential]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelCredential, db)

    async def get_by_provider(self, provider_id: uuid.UUID) -> ModelCredential | None:
        """按 provider_id 获取凭据。一个 provider 只有一条凭据。"""
        result = await self.db.execute(
            select(ModelCredential)
            .where(ModelCredential.provider_id == provider_id)
            .options(selectinload(ModelCredential.provider))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ModelCredential]:
        """获取所有凭据"""
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())

    async def list_by_provider_ids(self, provider_ids: set[uuid.UUID]) -> list[ModelCredential]:
        """按 provider_id 集合批量获取凭据"""
        if not provider_ids:
            return []
        result = await self.db.execute(
            select(ModelCredential)
            .where(ModelCredential.provider_id.in_(provider_ids))
        )
        return list(result.scalars().all())
