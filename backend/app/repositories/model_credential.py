"""
ModelCredential Repository
"""

import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model_credential import ModelCredential

from .base import BaseRepository


class ModelCredentialRepository(BaseRepository[ModelCredential]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelCredential, db)

    async def get_by_user_and_provider(
        self,
        user_id: Optional[str] = None,
        provider_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> ModelCredential | None:
        """根据供应商获取凭据（所有用户和工作空间可见）"""
        # 移除所有 user_id 和 workspace_id 过滤
        conditions = []
        if provider_id:
            conditions.append(ModelCredential.provider_id == provider_id)

        if conditions:
            result = await self.db.execute(select(ModelCredential).where(and_(*conditions)))
        else:
            result = await self.db.execute(select(ModelCredential))
        return result.scalar_one_or_none()

    async def get_by_provider(
        self,
        provider_id: uuid.UUID,
    ) -> ModelCredential | None:
        """根据供应商获取全局凭据（用于同步）"""
        result = await self.db.execute(
            select(ModelCredential).where(
                and_(
                    ModelCredential.provider_id == provider_id,
                    ModelCredential.user_id.is_(None),  # 只查询全局记录
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> list[ModelCredential]:
        """获取所有凭据（所有用户和工作空间可见）"""
        # 移除所有 user_id 和 workspace_id 过滤
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())

    async def list_all(self) -> list[ModelCredential]:
        """获取所有凭据（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())
