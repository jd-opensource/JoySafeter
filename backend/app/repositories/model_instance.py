"""
ModelInstance Repository
"""

import uuid
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model_instance import ModelInstance

from .base import BaseRepository


class ModelInstanceRepository(BaseRepository[ModelInstance]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelInstance, db)

    async def get_default(self) -> ModelInstance | None:
        """获取默认模型实例（全局）"""
        result = await self.db.execute(
            select(ModelInstance).where(ModelInstance.is_default).options(selectinload(ModelInstance.provider))
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, model_name: str) -> ModelInstance | None:
        """获取指定模型名的实例（全局）；若有多个同名实例，取最新的一个。"""
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
        provider_name: str,
        provider_id: Optional[uuid.UUID] = None,
        user_id: Optional[str] = None,
    ) -> ModelInstance | None:
        """根据供应商和模型名获取实例。优先返回全局实例，否则返回任意有效实例。"""
        conditions = [ModelInstance.model_name == model_name]

        if provider_id is not None:
            conditions.append(ModelInstance.provider_id == provider_id)
        else:
            conditions.append(ModelInstance.provider_id.is_(None))
            conditions.append(ModelInstance.provider_name == provider_name)

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
        """获取所有模型实例（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelInstance).options(selectinload(ModelInstance.provider)))
        return list(result.scalars().all())

    async def list_by_provider(
        self,
        provider_id: Optional[uuid.UUID] = None,
        provider_name: Optional[str] = None,
    ) -> list[ModelInstance]:
        """按供应商筛选模型实例。"""
        query = select(ModelInstance).options(selectinload(ModelInstance.provider))

        if provider_id is not None:
            query = query.where(ModelInstance.provider_id == provider_id)
        elif provider_name is not None:
            query = query.where(
                ModelInstance.provider_id.is_(None),
                ModelInstance.provider_name == provider_name,
            )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_provider(
        self,
        provider_id: Optional[uuid.UUID] = None,
        provider_name: Optional[str] = None,
    ) -> int:
        """按供应商筛选并统计模型实例数量。"""
        query = select(func.count()).select_from(ModelInstance)

        if provider_id is not None:
            query = query.where(ModelInstance.provider_id == provider_id)
        elif provider_name is not None:
            query = query.where(
                ModelInstance.provider_id.is_(None),
                ModelInstance.provider_name == provider_name,
            )

        result = await self.db.execute(query)
        return result.scalar() or 0
