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
        provider_name: Optional[str] = None,
    ) -> ModelCredential | None:
        """根据供应商获取凭据（支持用户级或全局）。"""
        if user_id:
            conditions = [ModelCredential.user_id == user_id]
        else:
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
        user_id: Optional[str] = None,
    ) -> ModelCredential | None:
        """根据供应商 ID 获取凭据（支持用户级或全局）"""
        if user_id:
            user_cond = ModelCredential.user_id == user_id
        else:
            user_cond = ModelCredential.user_id.is_(None)

        result = await self.db.execute(
            select(ModelCredential).where(
                and_(
                    ModelCredential.provider_id == provider_id,
                    user_cond,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_name(
        self,
        provider_name: str,
        user_id: Optional[str] = None,
    ) -> ModelCredential | None:
        """根据模板供应商名称获取凭据（支持用户级或全局）"""
        if user_id:
            user_cond = ModelCredential.user_id == user_id
        else:
            user_cond = ModelCredential.user_id.is_(None)

        result = await self.db.execute(
            select(ModelCredential).where(
                and_(
                    ModelCredential.provider_id.is_(None),
                    ModelCredential.provider_name == provider_name,
                    user_cond,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ModelCredential]:
        """获取所有凭据（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())
