"""WebSocket authentication utilities."""

from typing import Optional, Tuple

from fastapi import WebSocket
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models import User
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru
from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
from app.joysafeter_shared.database import AsyncSessionLocal
from app.joysafeter_shared.ids import UserId
from app.joysafeter_shared.security import decode_token


class WebSocketCloseCode:
    """Application-level WebSocket close codes."""

    UNAUTHORIZED = 4001
    FORBIDDEN = 4003
    NOT_FOUND = 4004


async def authenticate_websocket(websocket: WebSocket) -> Tuple[bool, Optional[UserId]]:
    """Authenticate a WebSocket connection via cookie or query-param token.

    Returns:
        A tuple of (is_authenticated, user_id).
    """
    token = None

    try:
        token = extract_token_from_cookies(websocket.cookies)
    except Exception as e:
        log_boundary_failure_loguru(
            logger,
            boundary="websocket_auth",
            code="WEBSOCKET_COOKIE_EXTRACTION_FAILED",
            message="WebSocket cookie extraction failed",
            operation="extract_cookie_token",
            error=e,
            retryable=False,
            user_action="retry_login",
        )

    if not token:
        token = websocket.query_params.get("token")

    if not token:
        return False, None

    payload = decode_token(token)
    if not payload or payload.type != "access":
        return False, None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == payload.sub))
        user = result.scalar_one_or_none()

    if not user or not user.is_active:
        return False, None

    return True, user.id


async def authenticate_websocket_with_user(websocket: WebSocket, db: AsyncSession) -> Tuple[bool, Optional[User]]:
    """Authenticate a WebSocket and load the active User from the database.

    Returns:
        A tuple of (is_authenticated, user) where user is None on failure.
    """
    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        return False, None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        return False, None

    if not user.is_active:
        return False, None

    return True, user


async def reject_websocket(
    websocket: WebSocket, code: int = WebSocketCloseCode.UNAUTHORIZED, reason: str = "Unauthorized"
) -> None:
    """Accept then immediately close a WebSocket with an error code."""
    try:
        await websocket.accept()
        await websocket.close(code=code, reason=reason)
    except Exception as e:
        log_boundary_failure_loguru(
            logger,
            boundary="websocket_auth",
            code="WEBSOCKET_REJECTION_FAILED",
            message="WebSocket rejection failed",
            operation="reject_websocket",
            error=e,
            data={"close_code": code},
        )
