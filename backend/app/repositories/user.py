"""
User Repository

Only basic user info queries; auth-related queries live in AuthUserRepository.
"""

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthUser as User

from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    User data access (aligned with the original project).

    Only basic user info queries; does not include auth-related column queries.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get a user by email."""
        return await self.get_by(email=email)

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID (text type)."""
        return await self.get_by(id=user_id)

    async def email_exists(self, email: str, exclude_id: Optional[str] = None) -> bool:
        """Check whether an email exists."""
        query = select(User).where(User.email == email)
        if exclude_id:
            query = query.where(User.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def search(self, keyword: str, limit: int = 20) -> List[User]:
        """Fuzzy-search users by email/name."""
        pattern = f"%{keyword}%"
        query = (
            select(User)
            .where(
                or_(
                    User.email.ilike(pattern),
                    User.name.ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_users(self, limit: int = 100) -> List[User]:
        """List users."""
        query = select(User).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())
