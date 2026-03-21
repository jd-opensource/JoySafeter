"""PlatformToken Repository."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_token import PlatformToken

from .base import BaseRepository


class PlatformTokenRepository(BaseRepository[PlatformToken]):
    def __init__(self, db: AsyncSession):
        super().__init__(PlatformToken, db)

    async def get_by_hash(self, token_hash: str) -> Optional[PlatformToken]:
        result = await self.db.execute(
            select(PlatformToken).where(PlatformToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> List[PlatformToken]:
        result = await self.db.execute(
            select(PlatformToken)
            .where(PlatformToken.user_id == user_id)
            .order_by(PlatformToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_active_by_user(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(PlatformToken).where(
                and_(
                    PlatformToken.user_id == user_id,
                    PlatformToken.is_active.is_(True),
                )
            )
        )
        return result.scalar() or 0
