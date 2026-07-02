"""
Common dependencies.
"""

import uuid
from typing import Annotated, Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.enums import OrgRole
from app.joysafeter_domain.models.joysafeter_auth import AuthUser as User
from app.joysafeter_domain.models.joysafeter_organization import Member as OrgMember
from app.joysafeter_domain.services.joysafeter_auth_service import AuthSessionService
from app.joysafeter_shared.common.app_errors import AccessDeniedError, AuthenticationError, NotFoundError
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
    Get the current user (login required).
    Support two authentication methods:
    1. JWT token (preferred): decode JWT token to obtain user ID
    2. Session token (backward-compatible): verify via auth.session table
    Also support token delivery via Cookie (prefer the configured cookie_name)
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

    # try JWT token first (JWT mode)
    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user is None:
            raise AuthenticationError("User not found", code="USER_NOT_FOUND")
        if not user.is_active:
            raise AuthenticationError("User is inactive", code="USER_INACTIVE")
        return user

    # if JWT validation fails, try as session token (backward-compatible)
    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        result = await db.execute(select(User).where(User.id == session.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise AuthenticationError("User not found", code="USER_NOT_FOUND")
        if not user.is_active:
            raise AuthenticationError("User is inactive", code="USER_INACTIVE")
        return user

    raise AuthenticationError("Could not validate credentials", code="INVALID_CREDENTIALS")


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

    # prefer JWT token
    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        return None

    # fall back to session token
    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        result = await db.execute(select(User).where(User.id == session.user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        return None

    return None


def require_org_role(min_role: OrgRole):
    """
    Verify the current user's role on the given organization_id
    (simple string comparison: owner > admin > member).
    Requires organization_id in path/query params.
    """
    role_order = [OrgRole.MEMBER, OrgRole.ADMIN, OrgRole.OWNER]

    def _rank(r: str) -> int:
        try:
            return role_order.index(OrgRole(r))
        except ValueError:
            return -1

    async def checker(
        organization_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.is_superuser:
            return current_user

        result = await db.execute(
            select(OrgMember).where(
                OrgMember.organization_id == organization_id,
                OrgMember.user_id == current_user.id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise AccessDeniedError("No access to organization", code="ORGANIZATION_ACCESS_DENIED")
        if _rank(member.role) < _rank(min_role):
            raise AccessDeniedError("Insufficient organization permission", code="ORGANIZATION_PERMISSION_DENIED")
        return current_user

    return Depends(checker)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_project_access():
    """
    Route-level dependency that resolves the project_id (from path param or
    X-Project-Id header) and verifies the current user has access via org membership.
    Returns the project_id as a string.
    """

    async def checker(
        request: Request,
        project_id: Optional[str] = None,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> str:
        if current_user.is_superuser:
            pid = project_id or request.headers.get("X-Project-Id")
            if not pid:
                raise NotFoundError("project_id required", code="PROJECT_ID_REQUIRED")
            return pid

        pid = project_id or request.headers.get("X-Project-Id")
        if not pid:
            raise NotFoundError("project_id required", code="PROJECT_ID_REQUIRED")

        from app.joysafeter_domain.models.joysafeter_project import Project

        result = await db.execute(select(Project).where(Project.id == pid))
        project = result.scalar_one_or_none()
        if not project:
            raise NotFoundError("Project not found", code="PROJECT_NOT_FOUND")

        result = await db.execute(
            select(OrgMember).where(
                OrgMember.organization_id == project.org_id,
                OrgMember.user_id == current_user.id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise AccessDeniedError("No access to project", code="PROJECT_ACCESS_DENIED")

        return pid

    return Depends(checker)
