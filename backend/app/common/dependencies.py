"""
Common dependencies.
"""

import uuid
from typing import Annotated, Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
from app.core.database import get_db
from app.core.security import decode_token
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.models.organization import Member as OrgMember
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository
from app.services.auth_session_service import AuthSessionService

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


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
            # prefer configured cookie_name, then try other possible names            cookie_token = (
                request.cookies.get(settings.cookie_name)  # prefer configured cookie name
                or request.cookies.get("session-token")
                or request.cookies.get("session_token")
                or request.cookies.get("access_token")
                or request.cookies.get("Authorization")
                or request.cookies.get("auth_token")
            )
    except Exception:
        pass
    token = token or cookie_token
    if not token:
        raise UnauthorizedException("Missing credentials")

    # try JWT token first (JWT mode)
    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user is None:
            raise UnauthorizedException("User not found")
        if not user.is_active:
            raise UnauthorizedException("User is inactive")
        return user

    # if JWT validation fails, try as session token (backward-compatible)
    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        result = await db.execute(select(User).where(User.id == session.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise UnauthorizedException("User not found")
        if not user.is_active:
            raise UnauthorizedException("User is inactive")
        return user

    raise UnauthorizedException("Could not validate credentials")


async def get_current_user_optional(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get the current user (optional; return None if not logged in). Also support token in Cookie."""
    cookie_token = None
    try:
        if request:
            # prefer configured cookie_name, then try other possible names            cookie_token = (
                request.cookies.get(settings.cookie_name)  # prefer configured cookie name
                or request.cookies.get("session-token")
                or request.cookies.get("session_token")
                or request.cookies.get("access_token")
                or request.cookies.get("Authorization")
                or request.cookies.get("auth_token")
            )
    except Exception:
        pass
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


# --------------------------------------------------------------------------- #
# Workspace / Organization role dependency helpers
# --------------------------------------------------------------------------- #
def _role_rank(role: WorkspaceMemberRole) -> int:
    order = [
        WorkspaceMemberRole.viewer,
        WorkspaceMemberRole.member,
        WorkspaceMemberRole.admin,
        WorkspaceMemberRole.owner,
    ]
    try:
        return order.index(role)
    except ValueError:
        return -1


def require_workspace_role(min_role: WorkspaceMemberRole):
    """
    Route-level dependency that verifies the current user's role on the given
    workspace_id is >= min_role. Requires workspace_id in path/query params.
    """

    async def checker(
        workspace_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.is_superuser:
            return current_user

        ws_repo = WorkspaceRepository(db)
        member_repo = WorkspaceMemberRepository(db)

        workspace = await ws_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        if workspace.owner_id == current_user.id:
            return current_user

        member = await member_repo.get_member(workspace_id, current_user.id)
        if not member:
            raise ForbiddenException("No access to workspace")

        if _role_rank(member.role) < _role_rank(min_role):
            raise ForbiddenException("Insufficient workspace permission")

        return current_user

    return Depends(checker)


def require_org_role(min_role: str):
    """
    Verify the current user's role on the given organization_id
    (simple string comparison: owner > admin > member).
    Requires organization_id in path/query params.
    """
    role_order = ["member", "admin", "owner"]

    def _rank(r: str) -> int:
        try:
            return role_order.index(r)
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
            raise ForbiddenException("No access to organization")
        if _rank(member.role) < _rank(min_role):
            raise ForbiddenException("Insufficient organization permission")
        return current_user

    return Depends(checker)


CurrentUser = Annotated[User, Depends(get_current_user)]
