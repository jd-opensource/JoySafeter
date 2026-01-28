"""
AuthSession Repository

管理会话记录（drizzle `session` 表）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession

from .base import BaseRepository


class AuthSessionRepository(BaseRepository[AuthSession]):
    """AuthSession 数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(AuthSession, db)

    async def get_by_token(self, token: str) -> Optional[AuthSession]:
        """根据 token 获取会话"""
        return await self.get_by(token=token)

    async def delete_by_token(self, token: str) -> int:
        """根据 token 删除会话，返回删除行数"""
        result = await self.db.execute(delete(AuthSession).where(AuthSession.token == token))
        await self.db.flush()
        return getattr(result, "rowcount", 0) or 0

    async def purge_expired(self, now: datetime) -> int:
        """清理过期会话，返回删除行数"""
        result = await self.db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
        await self.db.flush()
        return getattr(result, "rowcount", 0) or 0
