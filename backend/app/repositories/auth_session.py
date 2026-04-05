"""
AuthSession Repository

Manage session records (drizzle `session` table).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession

from .base import BaseRepository


class AuthSessionRepository(BaseRepository[AuthSession]):
    """AuthSession data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(AuthSession, db)

    async def get_by_token(self, token: str) -> Optional[AuthSession]:
        """Get a session by token."""
        return await self.get_by(token=token)

    async def delete_by_token(self, token: str) -> int:
        """Delete a session by token; return the number of deleted rows."""
        result = await self.db.execute(delete(AuthSession).where(AuthSession.token == token))
        await self.db.flush()
        return getattr(result, "rowcount", 0) or 0

    async def purge_expired(self, now: datetime) -> int:
        """Purge expired sessions; return the number of deleted rows."""
        result = await self.db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
        await self.db.flush()
        return getattr(result, "rowcount", 0) or 0
