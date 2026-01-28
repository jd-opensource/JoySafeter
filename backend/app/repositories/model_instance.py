"""
ModelInstance Repository
"""

import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_instance import ModelInstance

from .base import BaseRepository


class ModelInstanceRepository(BaseRepository[ModelInstance]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelInstance, db)

    async def get_default(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> ModelInstance | None:
        """获取默认模型实例（所有用户和工作空间可见）"""
        # 移除所有 user_id 和 workspace_id 过滤，返回第一个默认模型
        result = await self.db.execute(select(ModelInstance).where(ModelInstance.is_default))
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> list[ModelInstance]:
        """获取所有模型实例（所有用户和工作空间可见）"""
        # 移除所有 user_id 和 workspace_id 过滤
        result = await self.db.execute(select(ModelInstance))
        return list(result.scalars().all())

    # 获取指定模型名的实例
    async def get_by_name(
        self,
        model_name: str,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> ModelInstance | None:
        """获取指定模型名的实例（所有用户和工作空间可见）"""
        # 移除所有 workspace_id 过滤
        result = await self.db.execute(select(ModelInstance).where(ModelInstance.model_name == model_name))
        return result.scalar_one_or_none()

    async def get_by_provider_and_model(
        self,
        provider_id: uuid.UUID,
        model_name: str,
        user_id: Optional[str] = None,
    ) -> ModelInstance | None:
        """根据供应商和模型名获取实例

        优先返回全局记录（user_id 为 None），如果没有则返回用户记录
        """
        # 先尝试查找全局记录
        result = await self.db.execute(
            select(ModelInstance).where(
                and_(
                    ModelInstance.provider_id == provider_id,
                    ModelInstance.model_name == model_name,
                    ModelInstance.user_id.is_(None),  # 全局记录
                )
            )
        )
        instance = result.scalar_one_or_none()

        # 如果没有全局记录，且指定了 user_id，则查找用户记录
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

        # 如果还是没有，查找所有匹配的记录（不限制 user_id）
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

    async def list_all(self) -> list[ModelInstance]:
        """获取所有模型实例（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelInstance))
        return list(result.scalars().all())
