"""
AuthUser Repository
"""

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthUser

from .base import BaseRepository


class AuthUserRepository(BaseRepository[AuthUser]):
    """AuthUser 数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(AuthUser, db)

    async def get_by_email(self, email: str) -> Optional[AuthUser]:
        """根据邮箱获取用户"""
        return await self.get_by(email=email)

    async def get_by_reset_token(self, token: str) -> Optional[AuthUser]:
        """根据密码重置令牌获取用户"""
        result = await self.db.execute(
            select(AuthUser).where(
                AuthUser.password_reset_token == token,
                AuthUser.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_verify_token(self, token: str) -> Optional[AuthUser]:
        """根据邮箱验证令牌获取用户"""
        result = await self.db.execute(
            select(AuthUser).where(
                AuthUser.email_verify_token == token,
                AuthUser.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def search(self, keyword: str, limit: int = 20) -> list[AuthUser]:
        """按 email/name 模糊搜索活跃用户"""
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
