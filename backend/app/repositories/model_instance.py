"""
ModelInstance Repository
"""

import uuid
from typing import Dict, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model_instance import ModelInstance

from .base import BaseRepository


class ModelInstanceRepository(BaseRepository[ModelInstance]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelInstance, db)

    async def get_by_name(self, model_name: str) -> ModelInstance | None:
        """Get the instance for a model name (global); if multiple exist, return the newest."""
        result = await self.db.execute(
            select(ModelInstance)
            .where(ModelInstance.model_name == model_name)
            .options(selectinload(ModelInstance.provider))
            .order_by(ModelInstance.created_at.desc())
        )
        return result.scalars().first()

    async def get_best_instance(
        self,
        model_name: str,
        provider_id: uuid.UUID,
        provider_name: str = "",  # kept for call-site compatibility; unused
        user_id: Optional[str] = None,
    ) -> ModelInstance | None:
        """Get an instance by provider and model name. Prefer global instances; fall back to any valid one."""
        conditions = [
            ModelInstance.model_name == model_name,
            ModelInstance.provider_id == provider_id,
        ]

        result = await self.db.execute(
            select(ModelInstance).where(and_(*conditions)).options(selectinload(ModelInstance.provider))
        )
        instances = result.scalars().all()

        if not instances:
            return None

        for inst in instances:
            if inst.user_id is None:
                return inst

        return instances[0]

    async def list_all(self) -> list[ModelInstance]:
        """List all model instances (visible to all users and workspaces)."""
        result = await self.db.execute(select(ModelInstance).options(selectinload(ModelInstance.provider)))
        return list(result.scalars().all())

    async def list_by_provider(
        self,
        provider_id: uuid.UUID,
        provider_name: Optional[str] = None,  # kept for call-site compatibility; unused
    ) -> list[ModelInstance]:
        """Filter model instances by provider."""
        query = (
            select(ModelInstance)
            .options(selectinload(ModelInstance.provider))
            .where(ModelInstance.provider_id == provider_id)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_provider(
        self,
        provider_id: uuid.UUID,
    ) -> int:
        """Count model instances by provider."""
        query = select(func.count()).select_from(ModelInstance).where(ModelInstance.provider_id == provider_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def count_grouped_by_provider(self) -> Dict[uuid.UUID, int]:
        """Return instance counts grouped by provider in a single query."""
        query = select(ModelInstance.provider_id, func.count().label("cnt")).group_by(ModelInstance.provider_id)
        result = await self.db.execute(query)
        return {row.provider_id: row.cnt for row in result.all() if row.provider_id}
