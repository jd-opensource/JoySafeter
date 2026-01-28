"""Auth Session 服务 - 管理用户会话生命周期"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession, AuthUser
from app.models.organization import Member
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.auth_user import AuthUserRepository
from app.services.base import BaseService
from app.utils.datetime import utc_now


class AuthSessionService(BaseService):
    """Session 管理服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.user_repo = AuthUserRepository(db)
        self.session_repo = AuthSessionRepository(db)

    async def ensure_user(
        self,
        *,
        email: str,
        name: str,
        user_id: Optional[str] = None,
        email_verified: bool = False,
        image: Optional[str] = None,
        stripe_customer_id: Optional[str] = None,
        is_super_user: bool = False,
    ) -> AuthUser:
        """确保用户存在，不存在则创建；存在则同步关键字段"""
        user = await self.user_repo.get_by_email(email)
        if user:
            updated = False
            if name and user.name != name:
                user.name = name
                updated = True
            if image is not None and user.image != image:
                user.image = image
                updated = True
            if stripe_customer_id is not None and user.stripe_customer_id != stripe_customer_id:
                user.stripe_customer_id = stripe_customer_id
                updated = True
            if user.email_verified != email_verified:
                user.email_verified = email_verified
                updated = True
            if user.is_super_user != is_super_user:
                user.is_super_user = is_super_user
                updated = True
            if updated:
                await self.db.flush()
                await self.db.refresh(user)
            return user

        user = await self.user_repo.create(
            {
                "id": user_id or str(uuid.uuid4()),
                "name": name,
                "email": email,
                "email_verified": email_verified,
                "image": image,
                "stripe_customer_id": stripe_customer_id,
                "is_super_user": is_super_user,
            }
        )
        await self.db.flush()
        return user

    async def create_session(
        self,
        *,
        user: AuthUser,
        token: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuthSession:
        """创建会话并自动绑定活跃组织"""
        MAX_SESSIONS = 10
        existing_sessions = await self.list_user_sessions(user.id)

        if len(existing_sessions) >= MAX_SESSIONS:
            oldest_session = existing_sessions[-1]
            await self.invalidate_session(oldest_session.token)

        active_org_id = await self._resolve_active_org(user.id)
        session = await self.session_repo.create(
            {
                "user_id": user.id,
                "token": token,
                "expires_at": expires_at,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "active_organization_id": active_org_id,
            }
        )
        await self.commit()
        await self.db.refresh(session)
        return session

    async def get_session_by_token(self, token: str) -> Optional[AuthSession]:
        """获取有效会话，实现滑动过期机制"""
        session = await self.session_repo.get_by_token(token)
        if not session:
            return None

        now = utc_now()

        if session.expires_at < now:
            await self.session_repo.delete_by_token(token)
            await self.commit()
            return None

        INACTIVITY_TIMEOUT = 30 * 60
        MAX_SESSION_DURATION = 7 * 24 * 60 * 60

        if session.last_activity_at:
            inactivity = (now - session.last_activity_at).total_seconds()
            if inactivity > INACTIVITY_TIMEOUT:
                await self.session_repo.delete_by_token(token)
                await self.commit()
                return None

        session.last_activity_at = now

        session_age = (now - session.created_at).total_seconds()
        if session_age < MAX_SESSION_DURATION:
            new_expires = now + timedelta(minutes=30)
            max_expires = session.created_at + timedelta(seconds=MAX_SESSION_DURATION)
            session.expires_at = min(new_expires, max_expires)

        await self.commit()
        await self.db.refresh(session)
        return session

    async def invalidate_session(self, token: str) -> bool:
        """失效会话"""
        deleted = await self.session_repo.delete_by_token(token)
        await self.commit()
        return deleted > 0

    async def touch_session(self, token: str) -> Optional[AuthSession]:
        """刷新会话更新时间"""
        session = await self.session_repo.get_by_token(token)
        if not session:
            return None
        session.updated_at = utc_now()
        await self.commit()
        await self.db.refresh(session)
        return session

    async def purge_expired(self) -> int:
        """批量清理过期会话"""
        deleted = await self.session_repo.purge_expired(utc_now())
        await self.commit()
        return deleted

    async def list_user_sessions(self, user_id: str) -> list[AuthSession]:
        """列出用户所有会话"""
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.user_id == user_id).order_by(AuthSession.updated_at.desc())
        )
        return list(result.scalars().all())

    async def extend_session(self, token: str, new_expires_at: datetime) -> Optional[AuthSession]:
        """手动延长会话过期时间"""
        session = await self.session_repo.get_by_token(token)
        if not session:
            return None
        session.expires_at = new_expires_at
        await self.commit()
        await self.db.refresh(session)
        return session

    async def _resolve_active_org(self, user_id: str) -> Optional[str]:
        """获取用户所属的首个组织"""
        result = await self.db.execute(select(Member.organization_id).where(Member.user_id == user_id).limit(1))
        return result.scalar_one_or_none()
