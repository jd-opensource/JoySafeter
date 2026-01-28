"""WebSocket authentication utilities."""

from typing import Optional, Tuple

from fastapi import WebSocket
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.settings import settings
from app.models import User


class WebSocketCloseCode:
    UNAUTHORIZED = 4001
    FORBIDDEN = 4003
    NOT_FOUND = 4004


async def authenticate_websocket(websocket: WebSocket) -> Tuple[bool, Optional[str]]:
    token = None

    try:
        token = (
            websocket.cookies.get(settings.cookie_name)
            or websocket.cookies.get("session-token")
            or websocket.cookies.get("session_token")
            or websocket.cookies.get("access_token")
            or websocket.cookies.get("auth_token")
        )
    except Exception as e:
        logger.warning(f"WebSocket cookie extraction failed: {e}")

    if not token:
        token = websocket.query_params.get("token")

    if not token:
        return False, None

    payload = decode_token(token)
    if not payload:
        return False, None

    return True, payload.sub


async def authenticate_websocket_with_user(websocket: WebSocket, db: AsyncSession) -> Tuple[bool, Optional[User]]:
    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        return False, None

    result = await db.execute(select(User).where(User.id == str(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        return False, None

    if not user.is_active:
        return False, None

    return True, user


async def reject_websocket(
    websocket: WebSocket, code: int = WebSocketCloseCode.UNAUTHORIZED, reason: str = "Unauthorized"
) -> None:
    try:
        await websocket.accept()
        await websocket.close(code=code, reason=reason)
    except Exception as e:
        logger.warning(f"WebSocket rejection failed: {e}")
