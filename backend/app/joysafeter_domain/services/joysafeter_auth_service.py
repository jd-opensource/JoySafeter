"""
JoySafeter authentication services.

Merged from the former auth_session_service.py, auth_service.py,
oauth_service.py, and login_init.py (v1 cleanup consolidation):
  - AuthSessionService     — auth session persistence + active-org context
  - AuthService            — password login / signup / session issuance
  - OAuthService           — OAuth provider login / callback / linking
  - run_post_login_init()  — shared post-login bookkeeping + audit

Each former module's full body is kept verbatim below under a section banner;
redundant imports across sections are harmless.
"""

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners


# ============================================================================
# auth_session_service.py
# ============================================================================

"""Auth session service — manage user session lifecycle."""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthSession, AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.repositories.joysafeter_auth_session import AuthSessionRepository
from app.joysafeter_domain.repositories.joysafeter_auth_user import AuthUserRepository
from app.joysafeter_domain.services.base import BaseService
from app.joysafeter_shared.utils.datetime import utc_now


class AuthSessionService(BaseService):
    """Session management service."""

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
        """Ensure the user exists; create if missing, otherwise sync key fields."""
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
        """Create a session and automatically bind the active organization."""
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
        """Get a valid session, implementing sliding expiration."""
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
        """Invalidate a session."""
        deleted = await self.session_repo.delete_by_token(token)
        await self.commit()
        return deleted > 0

    async def touch_session(self, token: str) -> Optional[AuthSession]:
        """Refresh the session updated_at timestamp."""
        session = await self.session_repo.get_by_token(token)
        if not session:
            return None
        session.updated_at = utc_now()
        await self.commit()
        await self.db.refresh(session)
        return session

    async def purge_expired(self) -> int:
        """Purge expired sessions in bulk."""
        deleted = await self.session_repo.purge_expired(utc_now())
        await self.commit()
        return deleted

    async def list_user_sessions(self, user_id: str) -> list[AuthSession]:
        """List all sessions for a user."""
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.user_id == user_id).order_by(AuthSession.updated_at.desc())
        )
        return list(result.scalars().all())

    async def extend_session(self, token: str, new_expires_at: datetime) -> Optional[AuthSession]:
        """Manually extend the session expiration time."""
        session = await self.session_repo.get_by_token(token)
        if not session:
            return None
        session.expires_at = new_expires_at
        await self.commit()
        await self.db.refresh(session)
        return session

    async def _resolve_active_org(self, user_id: str) -> Optional[str]:
        """Get the first organization the user belongs to."""
        result = await self.db.execute(select(Member.organization_id).where(Member.user_id == user_id).limit(1))
        return result.scalar_one_or_none()


# ============================================================================
# auth_service.py
# ============================================================================

"""Auth service — registration, login, password reset, and related business logic."""

import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.enums import SecurityAuditEventType
from app.joysafeter_domain.models.joysafeter_auth import AuthSession, AuthUser
from app.joysafeter_domain.services.base import BaseService
from app.joysafeter_domain.services.joysafeter_email_service import email_service
from app.joysafeter_domain.services.joysafeter_security_audit_service import SecurityAuditService
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AuthenticationError,
    InternalServiceError,
    InvalidRequestError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.security import (
    generate_email_verify_token,
    generate_password_reset_token,
    get_password_hash,
    verify_password,
)


class AuthService(BaseService):
    """User authentication service."""

    _REFRESH_SESSION_PREFIX = "refresh:"

    # Refresh-token rotation grace window. When a refresh token is rotated we
    # keep a short-lived pointer from the old token to its replacement instead
    # of deleting it outright. Concurrent / multi-tab / replayed refresh calls
    # that still carry the just-rotated token land in this window and are
    # served the replacement instead of failing with REFRESH_TOKEN_INVALID.
    _REFRESH_GRACE_SECONDS = 60

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
        """Generate JWT access token, refresh token, and CSRF token."""
        from app.joysafeter_shared.cache.redis import RedisClient
        from app.joysafeter_shared.security import create_access_token, create_csrf_token, generate_refresh_token

        access_expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

        # Resolve org/project context to embed in JWT claims
        org_id = None
        project_id = None
        role = None
        try:
            import uuid as _uuid

            from sqlalchemy import select

            from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
            from app.joysafeter_domain.models.joysafeter_project import Project

            result = await self.db.execute(select(Member).where(Member.user_id == user_id).limit(1))
            membership = result.scalar_one_or_none()

            # Auto-create org + project for users who don't have one yet
            if not membership:
                new_org_id = str(_uuid.uuid4())
                org = Organization(id=new_org_id, name="Default", slug="default")
                self.db.add(org)
                membership = Member(
                    id=str(_uuid.uuid4()),
                    user_id=user_id,
                    organization_id=new_org_id,
                    role="owner",
                )
                self.db.add(membership)
                default_project = Project(
                    id=str(_uuid.uuid4()),
                    org_id=new_org_id,
                    name="Default",
                    slug="default",
                    is_default=True,
                )
                self.db.add(default_project)
                await self.db.flush()

            org_id = membership.organization_id
            role = membership.role

            proj_result = await self.db.execute(
                select(Project)
                .where(
                    Project.org_id == org_id,
                    Project.is_default.is_(True),
                )
                .limit(1)
            )
            project = proj_result.scalar_one_or_none()
            if not project:
                proj_result = await self.db.execute(select(Project).where(Project.org_id == org_id).limit(1))
                project = proj_result.scalar_one_or_none()
            if project:
                project_id = project.id
        except Exception as exc:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="AUTH_JWT_CONTEXT_RESOLVE_FAILED",
                    message="Failed to resolve org/project for JWT claims",
                    operation="resolve_jwt_context",
                    boundary="auth_service",
                    data={"user_id": user_id},
                    detail=exc.__class__.__name__,
                )
            ).debug("Failed to resolve org/project for JWT claims")

        # generate access token (JWT) with org/project context
        access_token = create_access_token(
            subject=user_id,
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
            org_id=org_id,
            project_id=project_id,
            role=role,
        )

        # generate refresh token (random string, stored in Redis and DB session fallback)
        refresh_token = generate_refresh_token()
        refresh_token_key = f"refresh_token:{refresh_token}"
        refresh_token_user_key = f"account_refresh_token:{user_id}"

        # store in Redis (only when Redis is available)
        if RedisClient.is_available():
            try:
                refresh_expire_seconds = int(refresh_expires.timestamp() - datetime.now(timezone.utc).timestamp())
                await RedisClient.set(refresh_token_key, user_id, expire=refresh_expire_seconds)
                await RedisClient.set(refresh_token_user_key, refresh_token, expire=refresh_expire_seconds)
            except Exception as exc:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="AUTH_REFRESH_TOKEN_REDIS_STORE_FAILED",
                        message="Failed to store refresh token in Redis",
                        operation="store_refresh_token",
                        boundary="auth_service",
                        data={"user_id": user_id},
                        detail=exc.__class__.__name__,
                    )
                ).debug("Failed to store refresh token in Redis")

        await self._store_refresh_session(refresh_token, user_id, refresh_expires)

        # generate CSRF token (JWT)
        csrf_token = create_csrf_token(user_id)

        return access_token, refresh_token, csrf_token, access_expires, refresh_expires

    def _refresh_session_token(self, refresh_token: str) -> str:
        """Namespace refresh tokens so they cannot be used as legacy access sessions."""
        return f"{self._REFRESH_SESSION_PREFIX}{refresh_token}"

    async def _store_refresh_session(
        self,
        refresh_token: str,
        user_id: str,
        refresh_expires: datetime,
    ) -> None:
        """Persist refresh token in DB as a durable fallback to Redis."""
        user = await self.user_repo.get_by(id=user_id)  # type: ignore[arg-type]
        if not user:
            logger.warning(f"Cannot persist refresh session: user not found user_id={user_id}")
            return

        await self.session_service.create_session(
            user=user,
            token=self._refresh_session_token(refresh_token),
            expires_at=refresh_expires,
        )

    async def _get_refresh_session_user_id(self, refresh_token: str) -> Optional[str]:
        """Resolve a refresh token from the durable DB session store."""
        session_token = self._refresh_session_token(refresh_token)
        session = await self.session_service.session_repo.get_by_token(session_token)
        if not session:
            return None

        now = datetime.now(timezone.utc)
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            await self.session_service.invalidate_session(session_token)
            return None

        session.last_activity_at = now
        await self.commit()
        return session.user_id

    async def _delete_refresh_token(self, refresh_token: str, user_id: str) -> None:
        """Delete the refresh token from Redis and the durable DB session store."""
        from app.joysafeter_shared.cache.redis import RedisClient

        redis_client = RedisClient.get_client()
        if redis_client:
            refresh_token_key = f"refresh_token:{refresh_token}"
            refresh_token_user_key = f"account_refresh_token:{user_id}"
            await redis_client.delete(refresh_token_key)
            await redis_client.delete(refresh_token_user_key)

        await self.session_service.invalidate_session(self._refresh_session_token(refresh_token))

    async def _rotate_refresh_token(self, refresh_token: str, user_id: str) -> None:
        """Retire a rotated refresh token, keeping a short grace pointer.

        The old token is removed from the live store but a
        ``refresh_token_grace:{token}`` marker is written with a short TTL so
        that a concurrent / multi-tab / replayed refresh still carrying it is
        served a fresh token set instead of failing. The durable DB session
        is invalidated immediately (the grace window is Redis-only); if Redis
        is unavailable we fall back to a hard delete.
        """
        from app.joysafeter_shared.cache.redis import RedisClient

        redis_client = RedisClient.get_client() if RedisClient.is_available() else None
        if redis_client:
            refresh_token_key = f"refresh_token:{refresh_token}"
            refresh_token_user_key = f"account_refresh_token:{user_id}"
            grace_key = f"refresh_token_grace:{refresh_token}"
            try:
                await redis_client.delete(refresh_token_key)
                await redis_client.delete(refresh_token_user_key)
                await RedisClient.set(grace_key, user_id, expire=self._REFRESH_GRACE_SECONDS)
            except Exception as exc:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="AUTH_REFRESH_TOKEN_REDIS_ROTATE_FAILED",
                        message="Failed to rotate refresh token in Redis",
                        operation="rotate_refresh_token",
                        boundary="auth_service",
                        data={"user_id": user_id},
                        detail=exc.__class__.__name__,
                    )
                ).debug("Failed to rotate refresh token in Redis")
        else:
            # No Redis: cannot keep a grace pointer, fall back to hard delete.
            pass

        await self.session_service.invalidate_session(self._refresh_session_token(refresh_token))

    def _build_jwt_login_response(
        self,
        user: AuthUser,
        access_token: str,
        refresh_token: str,
        csrf_token: str,
        access_expires: datetime,
        refresh_expires: datetime,
    ) -> dict:
        """Build login response (JWT mode)."""
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

    async def issue_login_tokens(self, user: AuthUser) -> dict:
        """Issue access/refresh/csrf tokens for an already authenticated user."""
        access_token, refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(user.id)
        return self._build_jwt_login_response(
            user, access_token, refresh_token, csrf_token, access_expires, refresh_expires
        )

    async def _build_login_response(
        self,
        user: AuthUser,
        session_token: str,
        expires_at: datetime,
        session: Optional[AuthSession] = None,
    ) -> dict:
        """Build login response (aligned with better-auth format)."""

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
        """Register a new user account, send a verification email, and return JWT tokens.

        Creates the user record and issues JWT access/refresh tokens so the user
        is logged in immediately. Org + project provisioning is handled by
        joysafeter auth on first API access.

        Args:
            email: Email address for the new account.
            name: Display name.
            password: Client-side hashed password.
            image: Optional profile image URL.
            is_super_user: Whether to grant super-user privileges.

        Returns:
            JWT login response dict containing user info and tokens.

        Raises:
            InvalidRequestError: If the email is already registered.
        """
        if await self.user_repo.get_by_email(email):
            raise InvalidRequestError(
                "Email already registered",
                code="USER_ALREADY_EXISTS",
                data={"email": email},
            )

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

        # Note: workspace provisioning removed — new users get org + project via joysafeter auth.

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
        """Authenticate a user by email and password, then return JWT tokens.

        Validates the password format, verifies credentials, checks account
        status, logs audit events on failure, and runs post-login initialization
        on success.

        Args:
            email: User's email address.
            password: Client-side hashed password (64-char hex string).
            skip_password_check: If True, bypass password verification (for
                OAuth/SSO flows).
            ip_address: Client IP address for audit logging.

        Returns:
            JWT login response dict containing user info and tokens.

        Raises:
            AuthenticationError: If credentials are invalid, the account is
                inactive, or email verification is required but not completed.
        """
        user = await self.user_repo.get_by_email(email)
        if not user:
            raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

        login_success = False
        if not skip_password_check:
            if not user.hashed_password:
                raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

            if not password:
                raise AuthenticationError("Incorrect email or password", code="MISSING_CREDENTIALS")

            # Validate password format (client-side hashed password)
            password = password.strip().lower()
            if len(password) != 64 or not all(c in "0123456789abcdef" for c in password):
                # Log the specific error internally without exposing to user
                logger.warning(f"Invalid password format received for login attempt: email={email}")
                raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

            stored_password = user.hashed_password.strip().lower()
            if len(stored_password) != 64 or not all(c in "0123456789abcdef" for c in stored_password):
                # Log the internal error but don't expose to user
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="AUTH_STORED_PASSWORD_FORMAT_INVALID",
                        message="Invalid stored password format",
                        operation="validate_stored_password_format",
                        boundary="auth_service",
                        data={"user_id": str(user.id)},
                        retryable=False,
                        user_action="check_data",
                    )
                ).warning("Invalid stored password format")
                raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

            password_match = verify_password(password, stored_password)

            if password_match:
                login_success = True
            else:
                try:
                    await self.audit_service.log_event(
                        event_type=SecurityAuditEventType.LOGIN_FAILURE,
                        event_status="failure",
                        ip_address=ip_address or "unknown",
                        user_id=user.id if user else None,
                        user_email=email,
                        details={},
                    )
                except Exception as exc:
                    logger.bind(
                        error=_oauth_service_error_payload(
                            code="AUTH_LOGIN_FAILURE_AUDIT_WRITE_FAILED",
                            message="Failed to log login failure audit event",
                            operation="write_login_failure_audit",
                            boundary="auth_service",
                            data={"user_id": user.id if user else None, "user_email": email},
                            detail=exc.__class__.__name__,
                        )
                    ).debug("Failed to log login failure audit event")

                await self.commit()
                raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")
        else:
            login_success = True

        if not user.is_active:
            raise AuthenticationError("Inactive user", code="USER_INACTIVE")

        if settings.require_email_verification and not user.email_verified:
            raise AccessDeniedError(
                "Email not verified. Please verify your email before logging in.",
                code="EMAIL_NOT_VERIFIED",
                data={"user_id": user.id, "email": user.email},
            )

        if login_success:
            pass  # run_post_login_init defined in this module

            await run_post_login_init(self.db, user, ip_address or "unknown")

        access_token, refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(user.id)
        return self._build_jwt_login_response(
            user, access_token, refresh_token, csrf_token, access_expires, refresh_expires
        )

    # ---------------------------------------------------------------- password reset
    async def request_password_reset(self, email: str) -> bool:
        """Send a password-reset email if the account exists.

        Always returns True to avoid leaking whether an email is registered.

        Args:
            email: Email address to send the reset link to.

        Returns:
            True unconditionally.
        """
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
        """Reset a user's password using a previously issued reset token.

        Args:
            token: The password-reset token from the email link.
            new_password: Client-side hashed new password.

        Returns:
            True on success.

        Raises:
            InvalidRequestError: If the token is invalid or expired.
        """
        user = await self.user_repo.get_by_reset_token(token)
        if not user:
            raise InvalidRequestError("Invalid or expired reset token", code="RESET_TOKEN_INVALID")
        if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
            raise InvalidRequestError("Reset token has expired", code="RESET_TOKEN_EXPIRED")
        user.hashed_password = get_password_hash(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        await self.commit()
        return True

    async def reset_password_for_current_user(self, user: AuthUser, new_password: str) -> bool:
        """Reset password for the current logged-in user (no old password required)."""
        if not user or not user.is_active:
            raise InvalidRequestError("User not found or inactive", code="USER_INVALID")
        user.hashed_password = get_password_hash(new_password)
        await self.commit()
        return True

    # ---------------------------------------------------------------- email verify
    async def verify_email(self, token: str) -> bool:
        """Verify a user's email address using the emailed verification token.

        Args:
            token: The email verification token.

        Returns:
            True on success.

        Raises:
            InvalidRequestError: If the token is invalid or expired.
        """
        user = await self.user_repo.get_by_verify_token(token)
        if not user:
            raise InvalidRequestError("Invalid or expired verification token", code="VERIFICATION_TOKEN_INVALID")
        if user.email_verify_expires and user.email_verify_expires < datetime.now(timezone.utc):
            raise InvalidRequestError("Verification token has expired", code="VERIFICATION_TOKEN_EXPIRED")
        user.email_verified = True
        user.email_verify_token = None
        user.email_verify_expires = None
        await self.commit()
        return True

    async def resend_verification_email(self, user: AuthUser) -> bool:
        """Generate a new verification token and resend the verification email.

        Args:
            user: The user requesting re-verification.

        Returns:
            True on success.

        Raises:
            InvalidRequestError: If the email is already verified.
        """
        if user.email_verified:
            raise InvalidRequestError("Email already verified", code="EMAIL_ALREADY_VERIFIED")
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
        """Refresh the access token.

        Uses rotation with a short grace window (``_REFRESH_GRACE_SECONDS``):
        the presented token is resolved from the live store first, then from
        the grace pointer of a just-rotated token. Either way a fresh token
        set is issued, so concurrent / multi-tab refreshes never fail with
        REFRESH_TOKEN_INVALID for a token that was valid moments ago.
        """
        from app.joysafeter_shared.cache.redis import RedisClient

        try:
            user_id = None
            redis_client = RedisClient.get_client() if RedisClient.is_available() else None
            if redis_client:
                refresh_token_key = f"refresh_token:{refresh_token}"
                user_id = await redis_client.get(refresh_token_key)
                if isinstance(user_id, bytes):
                    user_id = user_id.decode()

                # Grace window: token was rotated within the last
                # _REFRESH_GRACE_SECONDS by a concurrent / earlier refresh.
                if not user_id:
                    grace_key = f"refresh_token_grace:{refresh_token}"
                    user_id = await redis_client.get(grace_key)
                    if isinstance(user_id, bytes):
                        user_id = user_id.decode()

            if not user_id:
                user_id = await self._get_refresh_session_user_id(refresh_token)

            if not user_id:
                raise AuthenticationError("Invalid or expired refresh token", code="REFRESH_TOKEN_INVALID")

            # user_id from redis is a string, but AuthUser.id is also string
            # Use get_by method with id parameter
            user = await self.user_repo.get_by(id=user_id)  # type: ignore[arg-type]
            if not user or not user.is_active:
                await self._delete_refresh_token(refresh_token, user_id)
                raise AuthenticationError("Invalid user", code="USER_INVALID")

            access_token, new_refresh_token, csrf_token, access_expires, refresh_expires = await self._issue_jwt_tokens(
                user.id
            )

            # Rotate: keep the old token resolvable for a short grace window
            # instead of deleting it outright (kills the concurrent-refresh race).
            await self._rotate_refresh_token(refresh_token, user_id)

            return self._build_jwt_login_response(
                user, access_token, new_refresh_token, csrf_token, access_expires, refresh_expires
            )
        except AuthenticationError:
            raise
        except Exception:
            raise InternalServiceError(
                "Token refresh failed. Please login again.",
                code="TOKEN_REFRESH_FAILED",
            )

    # ---------------------------------------------------------------- misc
    async def get_user_by_id(self, user_id: str) -> Optional[AuthUser]:
        """Fetch a user by their unique ID.

        Args:
            user_id: The user's ID.

        Returns:
            The AuthUser if found, otherwise None.
        """
        return await self.user_repo.get_by(id=user_id)

    async def invalidate_session(self, token: str) -> bool:
        """Invalidate an active session by its token (logout).

        Args:
            token: The session token to invalidate.

        Returns:
            True if the session was found and invalidated, False otherwise.
        """
        return await self.session_service.invalidate_session(token)

    async def search_users(self, keyword: str, limit: int = 20) -> list[AuthUser]:
        """Search users by name or email keyword.

        Args:
            keyword: Search term to match against user names and emails.
            limit: Maximum number of results to return.

        Returns:
            List of matching AuthUser records.
        """
        return await self.user_repo.search(keyword, limit)

    async def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user account, preventing future logins.

        Args:
            user_id: ID of the user to deactivate.

        Returns:
            True if the user was found and deactivated, False if not found.
        """
        user = await self.user_repo.get_by(id=user_id)
        if not user:
            return False
        user.is_active = False
        await self.commit()
        return True

    async def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user account and all associated data.

        Args:
            user_id: ID of the user to delete.

        Returns:
            True if the user was found and deleted, False if not found.
        """
        user = await self.user_repo.get_by(id=user_id)
        if not user:
            return False
        await self.db.delete(user)
        await self.commit()
        return True


# ============================================================================
# oauth_service.py
# ============================================================================

"""
OAuth/OIDC service - business logic for OAuth login flow.

Responsibilities:
- Generate OAuth authorization URL
- Handle OAuth callbacks
- Exchange auth code for tokens
- Fetch user info
- Find or create users
- Bind OAuth accounts
"""

from datetime import datetime
from typing import Optional, Tuple, cast
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_oauth_account import OAuthAccount
from app.joysafeter_domain.services.base import BaseService
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.oauth import get_oauth_config
from app.joysafeter_shared.oauth.security import validate_oauth_endpoint_url

LOG_PREFIX = "[OAuthService]"

# State TTL (seconds)
OAUTH_STATE_EXPIRE_SECONDS = 600  # 10 minutes


def _oauth_service_error_payload(
    *,
    code: str,
    message: str,
    operation: str,
    provider_name: str | None = None,
    boundary: str = "oauth_service",
    source: str = "runtime",
    data: dict[str, object] | None = None,
    detail: str | None = None,
    retryable: bool = True,
    user_action: str | None = "retry",
) -> dict[str, object]:
    payload_data: dict[str, object] = {}
    if provider_name is not None:
        payload_data["provider_name"] = provider_name
    if data:
        payload_data.update(data)
    return async_boundary_error_payload(
        code=code,
        message=message,
        boundary=boundary,
        operation=operation,
        data=payload_data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    )


class OAuthService(BaseService):
    """OAuth auth service."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.user_repo = AuthUserRepository(db)
        self.oauth_config = get_oauth_config()

    def _provider_not_found(self, provider_name: str) -> InvalidRequestError:
        return InvalidRequestError(
            f"OAuth provider '{provider_name}' not found",
            code="OAUTH_PROVIDER_NOT_FOUND",
            data={"provider_name": provider_name},
        )

    def _endpoint_discovery_failed(self, provider_name: str, endpoint_type: str) -> InvalidRequestError:
        code_map = {
            "authorization": "OAUTH_DISCOVERY_FAILED",
            "token": "OAUTH_TOKEN_ENDPOINT_DISCOVERY_FAILED",
            "userinfo": "OAUTH_USERINFO_ENDPOINT_DISCOVERY_FAILED",
        }
        message_map = {
            "authorization": f"Failed to discover OAuth authorization endpoint for {provider_name}",
            "token": f"Failed to discover OAuth token endpoint for {provider_name}",
            "userinfo": f"Failed to discover OAuth userinfo endpoint for {provider_name}",
        }
        return InvalidRequestError(
            message_map[endpoint_type],
            code=code_map[endpoint_type],
            data={"provider_name": provider_name},
        )

    def _missing_endpoint(self, provider_name: str, endpoint_type: str) -> InvalidRequestError:
        code_map = {
            "authorization": "OAUTH_AUTHORIZE_URL_MISSING",
            "token": "OAUTH_TOKEN_URL_MISSING",
            "userinfo": "OAUTH_USERINFO_URL_MISSING",
        }
        message_map = {
            "authorization": f"No authorization URL configured for {provider_name}",
            "token": f"No token URL configured for {provider_name}",
            "userinfo": f"No userinfo URL configured for {provider_name}",
        }
        return InvalidRequestError(
            message_map[endpoint_type],
            code=code_map[endpoint_type],
            data={"provider_name": provider_name},
        )

    def _token_exchange_failed(self, provider_name: str) -> InvalidRequestError:
        return InvalidRequestError(
            f"Failed to exchange OAuth code for tokens for {provider_name}",
            code="OAUTH_TOKEN_EXCHANGE_FAILED",
            data={"provider_name": provider_name},
        )

    def _userinfo_fetch_failed(self, provider_name: str) -> InvalidRequestError:
        return InvalidRequestError(
            f"Failed to fetch OAuth user info for {provider_name}",
            code="OAUTH_USERINFO_FETCH_FAILED",
            data={"provider_name": provider_name},
        )

    # ==================== Authorization Flow ====================

    async def generate_authorization_url(
        self,
        provider_name: str,
        redirect_uri: str,
        state: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generate OAuth authorization URL.

        Args:
            provider_name: Provider key
            redirect_uri: Callback URL
            state: Optional state; auto-generated if missing

        Returns:
            Tuple of (authorization_url, state)

        Raises:
            InvalidRequestError: Provider not found or disabled
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise self._provider_not_found(provider_name)

        # Generate or reuse state
        if not state:
            state = secrets.token_urlsafe(32)

        # Store state in Redis (for callback validation)
        state_key = f"oauth_state:{state}"
        state_data = {
            "provider": provider_name,
            "redirect_uri": redirect_uri,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if RedisClient.is_available():
            try:
                import json

                await RedisClient.set(state_key, json.dumps(state_data), expire=OAUTH_STATE_EXPIRE_SECONDS)
            except Exception as e:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="OAUTH_SERVICE_STATE_STORE_FAILED",
                        message="Failed to store OAuth state in Redis",
                        operation="store_state",
                        provider_name=provider_name,
                        data={"state_key": state_key},
                        detail=e.__class__.__name__,
                    )
                ).warning(f"{LOG_PREFIX} Failed to store state in Redis")

        # Get authorize URL (may require OIDC Discovery)
        authorize_url: Optional[str] = provider.authorize_url or None
        if not authorize_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                authorize_url = cast(Optional[str], oidc_config.get("authorization_endpoint"))
            except Exception as e:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="OAUTH_AUTHORIZATION_DISCOVERY_UPSTREAM_FAILED",
                        message="OAuth authorization endpoint discovery failed",
                        operation="discover_authorization_endpoint",
                        provider_name=provider_name,
                        source="upstream",
                        data={"issuer": provider.issuer},
                        detail=e.__class__.__name__,
                    )
                ).error(f"{LOG_PREFIX} OIDC Discovery failed")
                raise self._endpoint_discovery_failed(provider_name, "authorization")

        if not authorize_url:
            raise self._missing_endpoint(provider_name, "authorization")

        # Build authorization URL params
        params = {
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": provider.scope,
            "state": state,
        }

        # Google requires access_type=offline for refresh_token
        if provider_name == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"

        authorization_url = f"{authorize_url}?{urlencode(params)}"
        logger.info(f"{LOG_PREFIX} Generated authorization URL for {provider_name}")

        return authorization_url, state

    async def validate_state(self, state: str) -> Optional[Dict[str, Any]]:
        """
        Validate OAuth state.

        Args:
            state: State value

        Returns:
            State data or None if invalid
        """
        state_key = f"oauth_state:{state}"

        if RedisClient.is_available():
            try:
                import json

                state_data_str = await RedisClient.get(state_key)
                if state_data_str:
                    # Delete used state (prevent replay attacks)
                    await RedisClient.delete(state_key)
                    return cast(Dict[str, Any], json.loads(state_data_str))
            except Exception as e:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="OAUTH_SERVICE_STATE_VALIDATE_FAILED",
                        message="Failed to validate OAuth state from Redis",
                        operation="validate_state",
                        data={"state_key": state_key},
                        detail=e.__class__.__name__,
                    )
                ).warning(f"{LOG_PREFIX} Failed to validate state from Redis")

        return None

    # ==================== Token Exchange ====================

    async def exchange_code_for_tokens(
        self,
        provider_name: str,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        Exchange auth code for tokens.

        Args:
            provider_name: Provider key
            code: Auth code
            redirect_uri: Callback URL

        Returns:
            Token response dict
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise self._provider_not_found(provider_name)

        # Get token URL
        token_url: Optional[str] = provider.token_url or None
        if not token_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                token_url = cast(Optional[str], oidc_config.get("token_endpoint"))
            except Exception as e:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="OAUTH_TOKEN_DISCOVERY_UPSTREAM_FAILED",
                        message="OAuth token endpoint discovery failed",
                        operation="discover_token_endpoint",
                        provider_name=provider_name,
                        source="upstream",
                        data={"issuer": provider.issuer},
                        detail=e.__class__.__name__,
                    )
                ).error(f"{LOG_PREFIX} OIDC Discovery failed")
                raise self._endpoint_discovery_failed(provider_name, "token")

        if not token_url:
            raise self._missing_endpoint(provider_name, "token")
        try:
            token_url = validate_oauth_endpoint_url(token_url, endpoint_type="token")
        except ValueError as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_TOKEN_URL_INVALID",
                    message="OAuth token URL failed security validation",
                    operation="validate_token_endpoint",
                    provider_name=provider_name,
                    source="api",
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Invalid token URL")
            raise InvalidRequestError(
                f"Invalid OAuth token URL for {provider_name}",
                code="OAUTH_TOKEN_URL_INVALID",
                data={"provider_name": provider_name},
            ) from None

        # Build request
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }

        headers = {"Accept": "application/json"}

        # GitHub: use client_secret_post
        if provider.token_endpoint_auth_method == "client_secret_post":
            # client_id/client_secret already in data
            pass
        else:
            # Default to client_secret_basic (HTTP Basic Auth)
            import base64

            credentials = base64.b64encode(f"{provider.client_id}:{provider.client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
            # Remove client credentials from data
            del data["client_id"]
            del data["client_secret"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(token_url, data=data, headers=headers)
                response.raise_for_status()

                # GitHub may return application/x-www-form-urlencoded
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    tokens: Dict[str, Any] = response.json()
                else:
                    # Parse URL-encoded response
                    from urllib.parse import parse_qs

                    parsed = parse_qs(response.text)
                    tokens = {k: v[0] for k, v in parsed.items()}

                logger.info(f"{LOG_PREFIX} Token exchange successful for {provider_name}")
                return tokens

        except httpx.HTTPStatusError as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_TOKEN_EXCHANGE_UPSTREAM_FAILED",
                    message="OAuth token exchange failed",
                    operation="exchange_code_for_tokens",
                    provider_name=provider_name,
                    source="upstream",
                    data={"status_code": e.response.status_code},
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Token exchange failed")
            raise self._token_exchange_failed(provider_name)
        except Exception as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_TOKEN_EXCHANGE_REQUEST_FAILED",
                    message="OAuth token exchange request failed",
                    operation="exchange_code_for_tokens",
                    provider_name=provider_name,
                    source="upstream",
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Token exchange error")
            raise self._token_exchange_failed(provider_name)

    # ==================== User Info ====================

    async def fetch_userinfo(
        self,
        provider_name: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """
        Fetch user info.

        Args:
            provider_name: Provider key
            access_token: Access token

        Returns:
            User info dict
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise self._provider_not_found(provider_name)

        # Get userinfo URL
        userinfo_url = provider.userinfo_url
        if not userinfo_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                userinfo_url = oidc_config.get("userinfo_endpoint")
            except Exception as e:
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="OAUTH_USERINFO_DISCOVERY_UPSTREAM_FAILED",
                        message="OAuth userinfo endpoint discovery failed",
                        operation="discover_userinfo_endpoint",
                        provider_name=provider_name,
                        source="upstream",
                        data={"issuer": provider.issuer},
                        detail=e.__class__.__name__,
                    )
                ).error(f"{LOG_PREFIX} OIDC Discovery failed")
                raise self._endpoint_discovery_failed(provider_name, "userinfo")

        if not userinfo_url:
            raise self._missing_endpoint(provider_name, "userinfo")
        try:
            userinfo_url = validate_oauth_endpoint_url(userinfo_url, endpoint_type="userinfo")
        except ValueError as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_USERINFO_URL_INVALID",
                    message="OAuth userinfo URL failed security validation",
                    operation="validate_userinfo_endpoint",
                    provider_name=provider_name,
                    source="api",
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Invalid userinfo URL")
            raise InvalidRequestError(
                f"Invalid OAuth userinfo URL for {provider_name}",
                code="OAUTH_USERINFO_URL_INVALID",
                data={"provider_name": provider_name},
            ) from None

        headers = {
            "Authorization": f"Bearer {access_token}",
            **provider.userinfo_headers,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(userinfo_url, headers=headers)
                response.raise_for_status()
                userinfo: Dict[str, Any] = response.json()

                # GitHub special case: fetch email separately
                if provider_name == "github" and not userinfo.get("email"):
                    email = await self._fetch_github_email(access_token)
                    if email:
                        userinfo["email"] = email

                logger.info(f"{LOG_PREFIX} Fetched userinfo for {provider_name}")
                return userinfo

        except httpx.HTTPStatusError as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_USERINFO_UPSTREAM_FAILED",
                    message="OAuth userinfo fetch failed",
                    operation="fetch_userinfo",
                    provider_name=provider_name,
                    source="upstream",
                    data={"status_code": e.response.status_code},
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Failed to fetch userinfo")
            raise self._userinfo_fetch_failed(provider_name)
        except Exception as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_USERINFO_REQUEST_FAILED",
                    message="OAuth userinfo request failed",
                    operation="fetch_userinfo",
                    provider_name=provider_name,
                    source="upstream",
                    detail=e.__class__.__name__,
                )
            ).error(f"{LOG_PREFIX} Userinfo fetch error")
            raise self._userinfo_fetch_failed(provider_name)

    async def _fetch_github_email(self, access_token: str) -> Optional[str]:
        """Get GitHub primary email."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                response.raise_for_status()
                emails = response.json()

                # Prefer primary & verified
                for email in emails:
                    if email.get("primary") and email.get("verified"):
                        return cast(Optional[str], email.get("email"))

                # Otherwise return any verified email
                for email in emails:
                    if email.get("verified"):
                        return cast(Optional[str], email.get("email"))

                return None
        except Exception as e:
            logger.bind(
                error=_oauth_service_error_payload(
                    code="OAUTH_GITHUB_EMAIL_FETCH_FAILED",
                    message="Failed to fetch GitHub primary email",
                    operation="fetch_github_email",
                    provider_name="github",
                    source="upstream",
                    detail=e.__class__.__name__,
                )
            ).warning(f"{LOG_PREFIX} Failed to fetch GitHub email")
            return None

    # ==================== User Management ====================

    def parse_userinfo(
        self,
        provider_name: str,
        userinfo: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Parse user info by user_mapping.

        Args:
            provider_name: Provider key
            userinfo: Raw user info

        Returns:
            Normalized user info
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise self._provider_not_found(provider_name)

        mapping = provider.user_mapping

        return {
            "provider_id": str(userinfo.get(mapping.get("id", "sub"), "")),
            "email": userinfo.get(mapping.get("email", "email")),
            "name": userinfo.get(mapping.get("name", "name")),
            "avatar": userinfo.get(mapping.get("avatar", "picture")),
        }

    async def find_or_create_user(
        self,
        provider_name: str,
        provider_account_id: str,
        email: Optional[str],
        name: Optional[str],
        avatar: Optional[str],
        tokens: Dict[str, Any],
        raw_userinfo: Dict[str, Any],
    ) -> Tuple[AuthUser, bool]:
        """
        Find or create OAuth user.

        Strategy:
        1. Find existing OAuth binding
        2. If auto_link_by_email, link by email
        3. If allow_registration, create new user

        Args:
            provider_name: Provider key
            provider_account_id: Provider user ID
            email: User email
            name: User name
            avatar: Avatar URL
            tokens: OAuth tokens
            raw_userinfo: Raw user info

        Returns:
            Tuple of (user, is_new_user)

        Raises:
            AuthenticationError: User missing and registration disabled
        """
        oauth_settings = self.oauth_config.settings

        # 1) Find existing OAuth binding
        oauth_account = await self._get_oauth_account(provider_name, provider_account_id)
        if oauth_account:
            user = await self.user_repo.get_by_id(oauth_account.user_id)
            if user:
                # Update OAuth tokens
                await self._update_oauth_account_tokens(oauth_account, tokens)
                logger.info(f"{LOG_PREFIX} Found existing OAuth binding for {provider_name}:{provider_account_id}")
                return user, False
            else:
                # Binding exists but user missing; clean up
                logger.bind(
                    error=_oauth_service_error_payload(
                        code="AUTH_OAUTH_ACCOUNT_USER_MISSING",
                        message="OAuth account exists but user is missing",
                        operation="cleanup_missing_oauth_user",
                        provider_name=provider_name,
                        data={"user_id": str(oauth_account.user_id)},
                        retryable=False,
                        user_action=None,
                    )
                ).warning(f"{LOG_PREFIX} OAuth account exists but user not found, cleaning up")
                await self._delete_oauth_account(oauth_account)

        # 2) Link by email if enabled
        if email and oauth_settings.auto_link_by_email:
            existing_user = await self.user_repo.get_by_email(email)
            if existing_user:
                # Create OAuth binding
                await self._create_oauth_account(
                    user_id=existing_user.id,
                    provider_name=provider_name,
                    provider_account_id=provider_account_id,
                    email=email,
                    tokens=tokens,
                    raw_userinfo=raw_userinfo,
                )
                logger.info(f"{LOG_PREFIX} Linked OAuth to existing user by email: {email}")
                return existing_user, False

        # 3) Create new user
        if not oauth_settings.allow_registration:
            raise AuthenticationError(
                "Registration via OAuth is not allowed. Please sign up first.", code="OAUTH_REGISTRATION_DISABLED"
            )

        if not email:
            raise InvalidRequestError(
                f"Email is required for registration. Please ensure your {provider_name} account has a verified email.",
                code="OAUTH_EMAIL_REQUIRED",
                data={"provider_name": provider_name},
            )

        # Create new user
        import uuid

        new_user = AuthUser(
            id=str(uuid.uuid4()),
            email=email,
            name=name or email.split("@")[0],
            image=avatar,
            hashed_password=None,  # SSO users have no password
            email_verified=True,  # OAuth email treated as verified
            is_active=True,
        )
        self.db.add(new_user)
        await self.db.flush()

        # Create OAuth binding
        await self._create_oauth_account(
            user_id=new_user.id,
            provider_name=provider_name,
            provider_account_id=provider_account_id,
            email=email,
            tokens=tokens,
            raw_userinfo=raw_userinfo,
        )

        logger.info(f"{LOG_PREFIX} Created new user via OAuth: {email}")
        return new_user, True

    # ==================== OAuth Account Management ====================

    async def _get_oauth_account(
        self,
        provider_name: str,
        provider_account_id: str,
    ) -> Optional[OAuthAccount]:
        """Find OAuth account binding."""
        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider_name,
            OAuthAccount.provider_account_id == provider_account_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_oauth_account(
        self,
        user_id: str,
        provider_name: str,
        provider_account_id: str,
        email: Optional[str],
        tokens: Dict[str, Any],
        raw_userinfo: Dict[str, Any],
    ) -> OAuthAccount:
        """Create OAuth account binding."""
        import uuid

        # Calculate token expiry
        expires_in = tokens.get("expires_in")
        token_expires_at = None
        if expires_in:
            token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        oauth_account = OAuthAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider_name,
            provider_account_id=provider_account_id,
            email=email,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_expires_at=token_expires_at,
            raw_userinfo=raw_userinfo,
        )
        self.db.add(oauth_account)
        await self.db.flush()

        logger.info(f"{LOG_PREFIX} Created OAuth account: {provider_name}:{provider_account_id}")
        return oauth_account

    async def _update_oauth_account_tokens(
        self,
        oauth_account: OAuthAccount,
        tokens: Dict[str, Any],
    ) -> None:
        """Update OAuth account tokens."""
        if tokens.get("access_token"):
            oauth_account.access_token = tokens["access_token"]

        if tokens.get("refresh_token"):
            oauth_account.refresh_token = tokens["refresh_token"]

        expires_in = tokens.get("expires_in")
        if expires_in:
            oauth_account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        await self.db.flush()

    async def _delete_oauth_account(self, oauth_account: OAuthAccount) -> None:
        """Delete OAuth account binding."""
        await self.db.delete(oauth_account)
        await self.db.flush()

    # ==================== User OAuth Account Queries ====================

    async def get_user_oauth_accounts(self, user_id: str) -> list[OAuthAccount]:
        """Get all OAuth bindings for a user."""
        stmt = select(OAuthAccount).where(OAuthAccount.user_id == user_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def unlink_oauth_account(
        self,
        user_id: str,
        provider_name: str,
    ) -> bool:
        """
        Unlink OAuth account.

        Args:
            user_id: User ID
            provider_name: Provider key

        Returns:
            Whether unlink succeeded

        Raises:
            InvalidRequestError: User would be unable to sign in
        """
        # Ensure user can still sign in after unlink
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise InvalidRequestError("User not found", code="USER_NOT_FOUND", data={"user_id": user_id})

        # Get all user OAuth bindings
        oauth_accounts = await self.get_user_oauth_accounts(user_id)
        target_account = next(
            (acc for acc in oauth_accounts if acc.provider == provider_name),
            None,
        )

        if not target_account:
            return False

        # Disallow unlink when no password and only one OAuth binding
        if not user.hashed_password and len(oauth_accounts) == 1:
            raise InvalidRequestError(
                "Cannot unlink the only OAuth account. Please set a password first.",
                code="OAUTH_LAST_ACCOUNT_UNLINK_FORBIDDEN",
            )

        await self._delete_oauth_account(target_account)
        logger.info(f"{LOG_PREFIX} Unlinked OAuth account: {provider_name} from user {user_id}")
        return True


# ============================================================================
# login_init.py
# ============================================================================

"""
Post-login initialization shared by normal login and OAuth login.

Update last-login time and IP, and record a login-success audit event.
Called by auth_service.login and oauth_callback to keep the logic centralized.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.joysafeter_domain.models.joysafeter_auth import AuthUser


async def run_post_login_init(db: AsyncSession, user: "AuthUser", ip_address: str) -> None:
    """
    Run unified post-login initialization: update last_login and audit.

    Consistent with auth_service.login and oauth_callback; maintained in one place.
    """
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip_address
    await db.commit()

    try:
        from app.joysafeter_domain.services.joysafeter_security_audit_service import SecurityAuditService

        audit_service = SecurityAuditService(db)
        await audit_service.log_event(
            event_type=SecurityAuditEventType.LOGIN_SUCCESS,
            event_status="success",
            ip_address=ip_address or "unknown",
            user_id=user.id,
            user_email=user.email,
        )
    except Exception as exc:
        logger.bind(
            error=_oauth_service_error_payload(
                code="AUTH_LOGIN_AUDIT_WRITE_FAILED",
                message="Failed to create security audit entry",
                operation="write_login_audit",
                boundary="auth_service",
                source="runtime",
                data={"user_id": user.id, "user_email": user.email},
                detail=exc.__class__.__name__,
            )
        ).warning("Failed to create security audit entry")

    # Note: workspace provisioning removed — new users get org + project via joysafeter auth.
