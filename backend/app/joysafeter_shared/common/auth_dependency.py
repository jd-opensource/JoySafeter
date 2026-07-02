"""Session/JWT authentication compatibility dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser as User
from app.joysafeter_shared.common.app_errors import AuthenticationError
from app.joysafeter_shared.common.dependencies import get_current_user
from app.joysafeter_shared.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login/form", auto_error=False)


@dataclass
class AuthContext:
    """Generic authentication result used by shared dependencies."""

    user: User


async def get_current_user_or_token(
    token: Optional[str] = Depends(oauth2_scheme),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Authenticate via the existing session/JWT path only."""
    if request is None:
        raise AuthenticationError("Authentication required", code="AUTH_REQUIRED")
    user = await get_current_user(token=token, request=request, db=db)
    return AuthContext(user=user)
