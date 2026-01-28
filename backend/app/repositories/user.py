"""
用户 Repository

只包含基础用户信息查询，认证相关查询在 AuthUserRepository 中。
"""

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthUser as User

from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    用户数据访问（对齐原始项目实现）

    只包含基础用户信息查询，不包含认证相关字段查询。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        return await self.get_by(email=email)

    async def get_by_id(self, user_id: str) -> Optional[User]:
        """根据 ID 获取用户（text 类型）"""
        return await self.get_by(id=user_id)

    async def email_exists(self, email: str, exclude_id: Optional[str] = None) -> bool:
        """检查邮箱是否存在"""
        query = select(User).where(User.email == email)
        if exclude_id:
            query = query.where(User.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def search(self, keyword: str, limit: int = 20) -> List[User]:
        """按 email/name 模糊搜索用户"""
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
        """获取用户列表"""
        query = select(User).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())
