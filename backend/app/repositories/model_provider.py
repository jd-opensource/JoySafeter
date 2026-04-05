"""
ModelProvider Repository
"""

from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_provider import ModelProvider

from .base import BaseRepository


class ModelProviderRepository(BaseRepository[ModelProvider]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelProvider, db)

    async def get_by_name(self, name: str) -> ModelProvider | None:
        """Get a provider by name."""
        result = await self.db.execute(select(ModelProvider).where(ModelProvider.name == name))
        return result.scalar_one_or_none()

    async def list_enabled(self) -> list[ModelProvider]:
        """List all enabled providers."""
        result = await self.db.execute(select(ModelProvider).where(ModelProvider.is_enabled))
        return list(result.scalars().all())

    async def list_by_type(self, provider_type: str) -> list[ModelProvider]:
        """List providers by type."""
        result = await self.db.execute(select(ModelProvider).where(ModelProvider.provider_type == provider_type))
        return list(result.scalars().all())

    async def count_all(self) -> int:
        """Get total provider count."""
        result = await self.db.execute(select(func.count()).select_from(ModelProvider))
        return result.scalar() or 0

    async def update_default_parameters(self, name: str, default_parameters: Dict[str, Any]) -> ModelProvider | None:
        """Update provider default parameters."""
        provider = await self.get_by_name(name)
        if not provider:
            return None

        provider.default_parameters = default_parameters
        await self.db.flush()
        await self.db.refresh(provider)
        return provider
