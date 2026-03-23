"""PlatformToken Repository."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_token import PlatformToken

from .base import BaseRepository


class PlatformTokenRepository(BaseRepository[PlatformToken]):
    def __init__(self, db: AsyncSession):
        super().__init__(PlatformToken, db)

    async def get_by_hash(self, token_hash: str) -> Optional[PlatformToken]:
        result = await self.db.execute(select(PlatformToken).where(PlatformToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def list_by_user_and_resource(
        self,
        user_id: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
    ) -> List[PlatformToken]:
        """Query tokens with optional resource filtering"""
        query = select(PlatformToken).where(PlatformToken.user_id == user_id, PlatformToken.is_active.is_(True))
        if resource_type is not None:
            query = query.where(PlatformToken.resource_type == resource_type)
        if resource_id is not None:
            query = query.where(PlatformToken.resource_id == resource_id)

        query = query.order_by(PlatformToken.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def deactivate_by_resource(self, resource_type: str, resource_id: str) -> int:
        from sqlalchemy import update

        query = (
            update(PlatformToken)
            .where(
                PlatformToken.resource_type == resource_type,
                PlatformToken.resource_id == resource_id,
                PlatformToken.is_active.is_(True),
            )
            .values(is_active=False)
        )
        result = await self.db.execute(query)
        await self.db.commit()
        return int(result.rowcount)  # type: ignore[attr-defined,no-any-return]

    async def list_by_user(self, user_id: str) -> List[PlatformToken]:
        result = await self.db.execute(
            select(PlatformToken)
            .where(PlatformToken.user_id == user_id, PlatformToken.is_active.is_(True))
            .order_by(PlatformToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_active_by_user(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(PlatformToken)
            .where(
                and_(
                    PlatformToken.user_id == user_id,
                    PlatformToken.is_active.is_(True),
                )
            )
        )
        return result.scalar() or 0
