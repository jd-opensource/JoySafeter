"""Dual-mode authentication: session/JWT + PlatformToken (sk_ prefix)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import UnauthorizedException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.platform_token import PlatformToken
from app.services.platform_token_service import TOKEN_PREFIX
from app.utils.string import hash_string_sha256

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Debounce interval for last_used_at updates (5 minutes)
_LAST_USED_DEBOUNCE_SECONDS = 300


@dataclass
class AuthContext:
    """Result of authentication — carries user + optional token scopes."""

    user: User
    token_scopes: Optional[List[str]] = None
    token_resource_type: Optional[str] = None
    token_resource_id: Optional[str] = None

    @property
    def is_token_auth(self) -> bool:
        return self.token_scopes is not None

    @property
    def scopes(self) -> Optional[List[str]]:
        return self.token_scopes


async def get_current_user_or_token(
    token: Optional[str] = Depends(oauth2_scheme),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """
    Authenticate via session/JWT or PlatformToken.

    If Bearer token starts with 'sk_', route to PlatformToken path.
    Otherwise, fall through to existing session/JWT auth.
    """
    # Try to extract token from cookie if not in header
    raw_token = token
    if not raw_token and request:
        from app.common.cookie_auth import extract_token_from_cookies

        raw_token = extract_token_from_cookies(request.cookies)

    # PlatformToken path
    if raw_token and raw_token.startswith(TOKEN_PREFIX):
        return await _authenticate_platform_token(raw_token, db)

    # Fall through to existing session/JWT auth
    if request is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Authentication required")
    user = await get_current_user(token=token, request=request, db=db)
    return AuthContext(user=user, token_scopes=None)


async def _authenticate_platform_token(
    raw_token: str,
    db: AsyncSession,
) -> AuthContext:
    """Verify a PlatformToken and return AuthContext with scopes."""
    token_hash = hash_string_sha256(raw_token)

    result = await db.execute(select(PlatformToken).where(PlatformToken.token_hash == token_hash))
    pt = result.scalar_one_or_none()

    if not pt:
        raise UnauthorizedException("Invalid API token")

    if not pt.is_active:
        raise UnauthorizedException("API token has been revoked")

    if pt.expires_at and pt.expires_at < datetime.now(timezone.utc):
        raise UnauthorizedException("API token has expired")

    # Debounce last_used_at update
    now = datetime.now(timezone.utc)
    if not pt.last_used_at or (now - pt.last_used_at).total_seconds() > _LAST_USED_DEBOUNCE_SECONDS:
        pt.last_used_at = now
        await db.commit()

    # Load the user — use the already-loaded relationship if available
    user = pt.user if pt.user else None
    if not user:
        user_result = await db.execute(select(User).where(User.id == pt.user_id))
        user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedException("Token owner account is inactive")

    return AuthContext(
        user=user,
        token_scopes=list(pt.scopes),
        token_resource_type=pt.resource_type,
        token_resource_id=str(pt.resource_id) if pt.resource_id else None,
    )
