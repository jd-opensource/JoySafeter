"""
Common dependencies.
"""

from typing import Annotated, Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser as User
from app.joysafeter_shared.common.app_errors import AuthenticationError
from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.security import decode_token

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login/form", auto_error=False)


async def get_current_user(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get the current user from an access JWT delivered by Bearer header or cookie.
    """
    cookie_token = None
    try:
        if request:
            cookie_token = extract_token_from_cookies(request.cookies)
    except Exception:
        logger.debug("Failed to read auth token from cookies", exc_info=True)
    token = token or cookie_token
    if not token:
        raise AuthenticationError("Missing credentials", code="MISSING_CREDENTIALS")

    payload = decode_token(token)
    if not payload or payload.type != "access":
        raise AuthenticationError("Could not validate credentials", code="INVALID_CREDENTIALS")

    result = await db.execute(select(User).where(User.id == str(payload.sub)))
    user = result.scalar_one_or_none()
    if user is None:
        raise AuthenticationError("User not found", code="USER_NOT_FOUND")
    if not user.is_active:
        raise AuthenticationError("User is inactive", code="USER_INACTIVE")
    return user


async def get_current_user_optional(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get the current user (optional; return None if not logged in). Also support token in Cookie."""
    cookie_token = None
    try:
        if request:
            cookie_token = extract_token_from_cookies(request.cookies)
    except Exception:
        logger.debug("Failed to read auth token from cookies", exc_info=True)
    token = token or cookie_token
    if not token:
        return None

    payload = decode_token(token)
    if not payload or payload.type != "access":
        return None

    result = await db.execute(select(User).where(User.id == str(payload.sub)))
    user = result.scalar_one_or_none()
    return user if user and user.is_active else None


CurrentUser = Annotated[User, Depends(get_current_user)]
