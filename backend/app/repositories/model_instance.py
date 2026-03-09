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

    async def get_by_provider_and_model(
        self,
        model_name: str,
        user_id: Optional[str] = None,
        provider_id: Optional[uuid.UUID] = None,
        provider_name: Optional[str] = None,
    ) -> ModelInstance | None:
        """根据供应商和模型名获取实例。支持 provider_id（用户派生）或 provider_name（模板）。"""
        if provider_id is not None:
            # 按 provider_id 查
            result = await self.db.execute(
                select(ModelInstance).where(
                    and_(
                        ModelInstance.provider_id == provider_id,
                        ModelInstance.model_name == model_name,
                        ModelInstance.user_id.is_(None),
                    )
                )
            )
            instance = result.scalar_one_or_none()
            if not instance and user_id:
                result = await self.db.execute(
                    select(ModelInstance).where(
                        and_(
                            ModelInstance.provider_id == provider_id,
                            ModelInstance.model_name == model_name,
                            ModelInstance.user_id == user_id,
                        )
                    )
                )
                instance = result.scalar_one_or_none()
            if not instance:
                result = await self.db.execute(
                    select(ModelInstance).where(
                        and_(
                            ModelInstance.provider_id == provider_id,
                            ModelInstance.model_name == model_name,
                        )
                    )
                )
                instance = result.scalar_one_or_none()
            return instance
        if provider_name is not None:
            # 按 provider_name 查（模板）
            result = await self.db.execute(
                select(ModelInstance).where(
                    and_(
                        ModelInstance.provider_id.is_(None),
                        ModelInstance.provider_name == provider_name,
                        ModelInstance.model_name == model_name,
                        ModelInstance.user_id.is_(None),
                    )
                )
            )
            instance = result.scalar_one_or_none()
            if not instance and user_id:
                result = await self.db.execute(
                    select(ModelInstance).where(
                        and_(
                            ModelInstance.provider_id.is_(None),
                            ModelInstance.provider_name == provider_name,
                            ModelInstance.model_name == model_name,
                            ModelInstance.user_id == user_id,
                        )
                    )
                )
                instance = result.scalar_one_or_none()
            return instance
        return None

    async def list_all(self) -> list[ModelInstance]:
        """获取所有模型实例（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelInstance))
        return list(result.scalars().all())
