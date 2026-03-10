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

    async def get_best_valid_credential(
        self,
        provider_name: str,
        provider_id: Optional[uuid.UUID] = None,
        user_id: Optional[str] = None,
    ) -> ModelCredential | None:
        """
        获取供应商的最优有效凭据。
        优先级：
        1. 匹配 user_id 的凭据
        2. 全局凭据 (user_id IS NULL)
        3. 任何人的有效凭据
        参数说明：如果传入 provider_id，则精确匹配该 ID；否则匹配 provider_id IS NULL 且 provider_name 等于传入值的记录。
        """
        conditions = [ModelCredential.is_valid == True]
        if provider_id:
            conditions.append(ModelCredential.provider_id == provider_id)
        else:
            conditions.append(ModelCredential.provider_id.is_(None))
            conditions.append(ModelCredential.provider_name == provider_name)

        result = await self.db.execute(select(ModelCredential).where(and_(*conditions)))
        credentials = result.scalars().all()

        if not credentials:
            return None

        # Priority 1: match user_id
        if user_id:
            for c in credentials:
                if c.user_id == user_id:
                    return c

        # Priority 2: user_id is None (Global)
        for c in credentials:
            if c.user_id is None:
                return c

        # Priority 3: any available
        return credentials[0]

    async def list_all(self) -> list[ModelCredential]:
        """获取所有凭据（所有用户和工作空间可见）"""
        result = await self.db.execute(select(ModelCredential).options(selectinload(ModelCredential.provider)))
        return list(result.scalars().all())
