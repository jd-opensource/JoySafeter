"""
ModelProvider Repository
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_provider import ModelProvider

from .base import BaseRepository


class ModelProviderRepository(BaseRepository[ModelProvider]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelProvider, db)

    async def get_by_name(self, name: str) -> ModelProvider | None:
        """根据名称获取供应商"""
        result = await self.db.execute(select(ModelProvider).where(ModelProvider.name == name))
        return result.scalar_one_or_none()

    async def list_enabled(self) -> list[ModelProvider]:
        """获取所有启用的供应商"""
        result = await self.db.execute(select(ModelProvider).where(ModelProvider.is_enabled))
        return list(result.scalars().all())
