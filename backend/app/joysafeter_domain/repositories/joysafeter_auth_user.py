"""
AuthUser Repository
"""

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_shared.ids import UserId
from app.joysafeter_shared.security import hash_security_token

from .base import BaseRepository


class AuthUserRepository(BaseRepository[AuthUser, UserId]):
    """AuthUser data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(AuthUser, db)

    async def get_by_id(self, user_id: UserId) -> Optional[AuthUser]:
        """Get a user by ID."""
        return await self.get_by(id=user_id)

    async def get_by_email(self, email: str) -> Optional[AuthUser]:
        """Get a user by email."""
        return await self.get_by(email=email)

    async def get_by_reset_token(self, token: str) -> Optional[AuthUser]:
        """Get a user by password reset token."""
        result = await self.db.execute(
            select(AuthUser).where(
                AuthUser.password_reset_token == hash_security_token(token),
                AuthUser.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_verify_token(self, token: str) -> Optional[AuthUser]:
        """Get a user by email verification token."""
        result = await self.db.execute(
            select(AuthUser).where(
                AuthUser.email_verify_token == hash_security_token(token),
                AuthUser.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def search(self, keyword: str, limit: int = 20) -> list[AuthUser]:
        """Fuzzy-search active users by email/name."""
        pattern = f"%{keyword}%"
        result = await self.db.execute(
            select(AuthUser)
            .where(
                AuthUser.is_active == True,  # noqa: E712
                or_(AuthUser.email.ilike(pattern), AuthUser.name.ilike(pattern)),
            )
            .limit(limit)
        )
        return list(result.scalars().all())
