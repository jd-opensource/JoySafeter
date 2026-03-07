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
        provider_id: Optional[uuid.UUID] = None,
        provider_name: Optional[str] = None,
    ) -> ModelCredential | None:
        """根据供应商获取凭据（全局）。支持按 provider_id 或 provider_name（模板）查询。"""
        conditions = [ModelCredential.user_id.is_(None)]
        if provider_id is not None:
            conditions.append(ModelCredential.provider_id == provider_id)
        if provider_name is not None:
            conditions.append(ModelCredential.provider_name == provider_name)
        if provider_id is None and provider_name is None:
            return None
        result = await self.db.execute(select(ModelCredential).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def get_by_provider(
        self,
        provider_id: uuid.UUID,
    ) -> ModelCredential | None:
        """根据供应商 ID 获取全局凭据（用户派生供应商）"""
        result = await self.db.execute(
            select(ModelCredential).where(
                and_(
                    ModelCredential.provider_id == provider_id,
                    ModelCredential.user_id.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_name(
        self,
        provider_name: str,
    ) -> ModelCredential | None:
        """根据模板供应商名称获取全局凭据（provider_id 为空、provider_name 匹配）"""
        result = await self.db.execute(
            select(ModelCredential).where(
                and_(
                    ModelCredential.provider_id.is_(None),
                    ModelCredential.provider_name == provider_name,
                    ModelCredential.user_id.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ModelCredential]:
        """获取所有凭据（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())
