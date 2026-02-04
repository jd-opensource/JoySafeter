"""认证服务 - 注册、登录、密码重置等业务逻辑"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, UnauthorizedException
from app.core.security import (
    generate_email_verify_token,
    generate_password_reset_token,
    get_password_hash,
    verify_password,
)
from app.core.settings import settings
from app.models.auth import AuthSession, AuthUser
from app.repositories.auth_user import AuthUserRepository
from app.services.auth_session_service import AuthSessionService
from app.services.base import BaseService
from app.services.email_service import email_service
from app.services.security_audit_service import SecurityAuditService


class AuthService(BaseService):
    """用户认证服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.user_repo = AuthUserRepository(db)
        self.session_service = AuthSessionService(db)
        self.audit_service = SecurityAuditService(db)

    # ------------------------------------------------------------------ utils
    def _issue_token(self, user_id: str) -> tuple[str, datetime]:
        expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        token = secrets.token_urlsafe(32)
        return token, expires

    async def _issue_jwt_tokens(self, user_id: str) -> tuple[str, str, str, datetime, datetime]:
        """生成 JWT access token、refresh token 和 CSRF token"""
        from app.core.redis import RedisClient
        from app.core.security import create_access_token, create_csrf_token, generate_refresh_token

        access_expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

        # 生成 access token (JWT)
        access_token = create_access_token(
            subject=user_id, expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
        )

        # 生成 refresh token (随机字符串，存储在 Redis)
        refresh_token = generate_refresh_token()
        refresh_token_key = f"refresh_token:{refresh_token}"
        refresh_token_user_key = f"account_refresh_token:{user_id}"

        # 存储到 Redis（仅在 Redis 可用时）
        if RedisClient.is_available():
            try:
                refresh_expire_seconds = int(refresh_expires.timestamp() - datetime.now(timezone.utc).timestamp())
                await RedisClient.set(refresh_token_key, user_id, expire=refresh_expire_seconds)
                await RedisClient.set(refresh_token_user_key, refresh_token, expire=refresh_expire_seconds)
            except Exception:
                pass

        # 生成 CSRF token (JWT)
        csrf_token = create_csrf_token(user_id)

        return access_token, refresh_token, csrf_token, access_expires, refresh_expires

    async def _delete_refresh_token(self, refresh_token: str, user_id: str) -> None:
        """删除 Redis 中的 refresh token"""
        from app.core.redis import RedisClient

        redis_client = RedisClient.get_client()
        if redis_client:
            refresh_token_key = f"refresh_token:{refresh_token}"
            refresh_token_user_key = f"account_refresh_token:{user_id}"
            await redis_client.delete(refresh_token_key)
            await redis_client.delete(refresh_token_user_key)

    def _build_jwt_login_response(
        self,
        user: AuthUser,
        access_token: str,
        refresh_token: str,
        csrf_token: str,
        access_expires: datetime,
        refresh_expires: datetime,
    ) -> dict:
        """构建登录响应（JWT 模式）"""
        response = {
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "image": user.image,
                "emailVerified": user.email_verified,
                "isSuperUser": user.is_super_user,
                "createdAt": user.created_at.isoformat() if user.created_at else None,
                "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
            },
            "access_token": access_token,
            "refresh_token": refresh_token,
            "csrf_token": csrf_token,
            "token_type": "bearer",
            "expires_in": int((access_expires - datetime.now(timezone.utc)).total_seconds()),
        }
        return response

    async def _build_login_response(
        self,
        user: AuthUser,
        session_token: str,
        expires_at: datetime,
        session: Optional[AuthSession] = None,
    ) -> dict:
        """构建登录响应（对齐 better-auth 格式）"""

        response: Dict[str, Any] = {
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "image": user.image,
                "emailVerified": user.email_verified,
                "isSuperUser": user.is_super_user,
                "createdAt": user.created_at.isoformat() if user.created_at else None,
                "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
            },
        }

        if session:
            response["session"] = {
                "id": session.id,
                "token": session.token,
                "expiresAt": session.expires_at.isoformat() if session.expires_at else None,
                "userId": session.user_id,
                "activeOrganizationId": session.active_organization_id,
                "ipAddress": session.ip_address,
                "userAgent": session.user_agent,
                "createdAt": session.created_at.isoformat() if session.created_at else None,
                "updatedAt": session.updated_at.isoformat() if session.updated_at else None,
            }
        else:
            response["session"] = {
                "token": session_token,
                "expiresAt": expires_at.isoformat() if expires_at else None,
            }
            response["access_token"] = session_token
            response["token_type"] = "bearer"
            response["expires_in"] = int((expires_at - datetime.now(timezone.utc)).total_seconds())

        return response

    # ---------------------------------------------------------------- register/login
    async def register(
        self,
        *,
        email: str,
        name: str,
        password: str,
        image: Optional[str] = None,
        is_super_user: bool = False,
    ) -> dict:
        if await self.user_repo.get_by_email(email):
            raise BadRequestException("Email already registered")

        user = await self.user_repo.create(
            {
                "name": name,
                "email": email,
                "hashed_password": get_password_hash(password),
                "image": image,
                "is_super_user": is_super_user,
                "email_verified": False,
            }
        )
        try:
            token_verify, expires_verify = generate_email_verify_token()
            user.email_verify_token = token_verify
            user.email_verify_expires = expires_verify
            await self.commit()
            await email_service.send_email_verification(
                to_email=user.email,
                username=user.name,
                verify_token=token_verify,
            )
        except Exception:
            await self.commit()

        try:
            from app.services.workspace_service import WorkspaceService

            workspace_service = WorkspaceService(self.db)
            await workspace_service.ensure_personal_workspace(user)
        except Exception:
            pass

        access_token, refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(user.id)
        return self._build_jwt_login_response(
            user, access_token, refresh_token, csrf_token, access_expires, refresh_expires
        )

    async def login(
        self,
        *,
        email: str,
        password: Optional[str] = None,
        skip_password_check: bool = False,
        ip_address: Optional[str] = None,
    ) -> dict:
        user = await self.user_repo.get_by_email(email)
        if not user:
            raise UnauthorizedException("Incorrect email or password")

        login_success = False
        if not skip_password_check:
            if not user.hashed_password:
                raise UnauthorizedException("Incorrect email or password")

            if not password:
                raise UnauthorizedException("Incorrect email or password")

            # Validate password format (client-side hashed password)
            password = password.strip().lower()
            if len(password) != 64 or not all(c in "0123456789abcdef" for c in password):
                # Log the specific error internally without exposing to user
                logger.warning(f"Invalid password format received for login attempt: email={email}")
                raise UnauthorizedException("Incorrect email or password")

            stored_password = user.hashed_password.strip().lower()
            if len(stored_password) != 64 or not all(c in "0123456789abcdef" for c in stored_password):
                # Log the internal error but don't expose to user
                logger.error(f"Invalid stored password format for user: {user.id}")
                raise UnauthorizedException("Incorrect email or password")

            password_match = verify_password(password, stored_password)

            if password_match:
                login_success = True
            else:
                try:
                    await self.audit_service.log_event(
                        event_type="login_failure",
                        event_status="failure",
                        ip_address=ip_address or "unknown",
                        user_id=user.id if user else None,
                        user_email=email,
                        details={},
                    )
                except Exception:
                    pass

                await self.commit()
                raise UnauthorizedException("Incorrect email or password")
        else:
            login_success = True

        if not user.is_active:
            raise UnauthorizedException("Inactive user")

        if settings.require_email_verification and not user.email_verified:
            raise UnauthorizedException("Email not verified. Please verify your email before logging in.", code=403)

        if login_success:
            from app.services.login_init import run_post_login_init

            await run_post_login_init(self.db, user, ip_address or "unknown")

        access_token, refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(user.id)
        return self._build_jwt_login_response(
            user, access_token, refresh_token, csrf_token, access_expires, refresh_expires
        )

    # ---------------------------------------------------------------- password reset
    async def request_password_reset(self, email: str) -> bool:
        user = await self.user_repo.get_by_email(email)
        if not user:
            return True
        token, expires = generate_password_reset_token()
        user.password_reset_token = token
        user.password_reset_expires = expires
        await self.commit()
        await email_service.send_password_reset_email(
            to_email=user.email,
            username=user.name,
            reset_token=token,
        )
        return True

    async def reset_password(self, token: str, new_password: str) -> bool:
        user = await self.user_repo.get_by_reset_token(token)
        if not user:
            raise BadRequestException("Invalid or expired reset token")
        if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
            raise BadRequestException("Reset token has expired")
        user.hashed_password = get_password_hash(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        await self.commit()
        return True

    async def reset_password_for_current_user(self, user: AuthUser, new_password: str) -> bool:
        """Reset password for the current logged-in user (no old password required)."""
        if not user or not user.is_active:
            raise BadRequestException("User not found or inactive")
        user.hashed_password = get_password_hash(new_password)
        await self.commit()
        return True

    # ---------------------------------------------------------------- email verify
    async def verify_email(self, token: str) -> bool:
        user = await self.user_repo.get_by_verify_token(token)
        if not user:
            raise BadRequestException("Invalid or expired verification token")
        if user.email_verify_expires and user.email_verify_expires < datetime.now(timezone.utc):
            raise BadRequestException("Verification token has expired")
        user.email_verified = True
        user.email_verify_token = None
        user.email_verify_expires = None
        await self.commit()
        return True

    async def resend_verification_email(self, user: AuthUser) -> bool:
        if user.email_verified:
            raise BadRequestException("Email already verified")
        token, expires = generate_email_verify_token()
        user.email_verify_token = token
        user.email_verify_expires = expires
        await self.commit()
        await email_service.send_email_verification(
            to_email=user.email,
            username=user.name,
            verify_token=token,
        )
        return True

    # ---------------------------------------------------------------- refresh token
    async def refresh_token(self, refresh_token: str) -> dict:
        """刷新 access token"""
        from app.core.redis import RedisClient

        if not RedisClient.is_available():
            raise UnauthorizedException("Token refresh service unavailable. Please login again.", code=503)

        redis_client = RedisClient.get_client()
        if not redis_client:
            raise UnauthorizedException("Token refresh service unavailable. Please login again.", code=503)

        try:
            refresh_token_key = f"refresh_token:{refresh_token}"
            user_id = await redis_client.get(refresh_token_key)

            if not user_id:
                raise UnauthorizedException("Invalid or expired refresh token")

            # user_id from redis is a string, but AuthUser.id is also string
            # Use get_by method with id parameter
            user = await self.user_repo.get_by(id=user_id)  # type: ignore[arg-type]
            if not user or not user.is_active:
                await self._delete_refresh_token(refresh_token, user_id)
                raise UnauthorizedException("Invalid user")

            access_token, new_refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(
                user.id
            )

            await self._delete_refresh_token(refresh_token, user_id)

            return self._build_jwt_login_response(
                user, access_token, new_refresh_token, csrf_token, access_expires, refresh_expires
            )
        except UnauthorizedException:
            raise
        except Exception:
            raise UnauthorizedException("Token refresh failed. Please login again.", code=500)

    # ---------------------------------------------------------------- misc
    async def get_user_by_id(self, user_id: str) -> Optional[AuthUser]:
        return await self.user_repo.get_by(id=user_id)

    async def invalidate_session(self, token: str) -> bool:
        return await self.session_service.invalidate_session(token)

    async def search_users(self, keyword: str, limit: int = 20) -> list[AuthUser]:
        return await self.user_repo.search(keyword, limit)

    async def deactivate_user(self, user_id: str) -> bool:
        user = await self.user_repo.get_by(id=user_id)
        if not user:
            return False
        user.is_active = False
        await self.commit()
        return True

    async def delete_user(self, user_id: str) -> bool:
        user = await self.user_repo.get_by(id=user_id)
        if not user:
            return False
        await self.db.delete(user)
        await self.commit()
        return True
