"""
User service.

Handle basic user information management only; authentication operations live in AuthService.
"""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.auth import AuthUser as User
from app.repositories.user import UserRepository

from .base import BaseService


class UserService(BaseService):
    """
    User service (aligned with the original project implementation).

    Only contain basic user information management, no authentication features.
    Authentication features (password, email verification, etc.) live in AuthService.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.user_repo = UserRepository(db)

    # ---------------------------------------------------------------- user queries
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID."""
        return await self.user_repo.get_by_id(user_id)

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email."""
        return await self.user_repo.get_by_email(email)

    async def search_users(self, keyword: str, limit: int = 20) -> List[User]:
        """Search users (by email/name)."""
        return await self.user_repo.search(keyword, limit)

    async def list_users(self, limit: int = 100) -> List[User]:
        """Get a list of users."""
        return await self.user_repo.list_users(limit)

    # ---------------------------------------------------------------- user creation and update
    async def create_user(
        self,
        *,
        email: str,
        name: str,
        image: Optional[str] = None,
        is_super_user: bool = False,
        email_verified: bool = False,
    ) -> User:
        """
        Create a new user.

        Note: does not include password setup; password operations live in AuthService.
        """
        if await self.user_repo.email_exists(email):
            raise BadRequestException("Email already registered")

        user_data = {
            "name": name,
            "email": email,
            "image": image,
            "is_super_user": is_super_user,
            "email_verified": email_verified,
        }

        user = await self.user_repo.create(user_data)
        await self.commit()

        return user

    async def update_user(
        self,
        user: User,
        *,
        name: Optional[str] = None,
        email: Optional[str] = None,
        image: Optional[str] = None,
        is_super_user: Optional[bool] = None,
        email_verified: Optional[bool] = None,
        stripe_customer_id: Optional[str] = None,
    ) -> User:
        """Update user information."""
        if name is not None:
            user.name = name
        if email is not None:
            if email != user.email and await self.user_repo.email_exists(email, exclude_id=user.id):
                raise BadRequestException("Email already registered")
            user.email = email
        if image is not None:
            user.image = image
        if is_super_user is not None:
            user.is_super_user = is_super_user
        if email_verified is not None:
            user.email_verified = email_verified
        if stripe_customer_id is not None:
            user.stripe_customer_id = stripe_customer_id

        await self.commit()
        return user

    async def update_email_verified(self, user: User, verified: bool) -> User:
        """Update email verification status."""
        user.email_verified = verified
        await self.commit()
        return user

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")

        import uuid as uuid_lib

        user_uuid = uuid_lib.UUID(user_id) if isinstance(user_id, str) else user_id
        await self.user_repo.delete(user_uuid)
        await self.commit()
        return True
