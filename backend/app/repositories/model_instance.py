"""
ModelInstance Repository
"""

import uuid
from typing import Optional

from sqlalchemy import and_, select
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
        """根据供应商和模型名获取实例。优先匹配用户级，其次全局，最后匹配任意有效。"""
        conditions = [ModelInstance.model_name == model_name]

        if provider_id is not None:
            conditions.append(ModelInstance.provider_id == provider_id)
        else:
            conditions.append(ModelInstance.provider_id.is_(None))
            conditions.append(ModelInstance.provider_name == provider_name)

        result = await self.db.execute(select(ModelInstance).where(and_(*conditions)))
        instances = result.scalars().all()

        if not instances:
            return None

        # Priority 1: match user_id
        if user_id:
            for inst in instances:
                if inst.user_id == user_id:
                    return inst

        # Priority 2: user_id is None (Global)
        for inst in instances:
            if inst.user_id is None:
                return inst

        # Priority 3: any available
        return instances[0]

    async def list_all(self) -> list[ModelInstance]:
        """获取所有模型实例（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelInstance))
        return list(result.scalars().all())
