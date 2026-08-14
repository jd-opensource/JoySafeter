"""
JoySafeter auth dependencies for FastAPI.

Provides get_joysafeter_auth_context (the main dependency) and convenience
wrappers require_joysafeter_write / require_joysafeter_admin.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import AccessDeniedError, AuthenticationError, ResourceConflictError
from app.joysafeter_shared.database import get_db

from .context import (
    JoySafeterAuthContext,
    JoySafeterRole,
    ProjectCapability,
    effective_project_capability,
)

# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


# Map a stored org-member role string (from the member table) to JoySafeterRole.
def _map_org_role(role_value: str) -> JoySafeterRole:
    """Convert a stored org-member role string to a JoySafeterRole."""
    return JoySafeterRole.normalize(role_value)


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash a raw API key to match stored key_hash."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Main dependency
# ---------------------------------------------------------------------------


async def get_joysafeter_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JoySafeterAuthContext:
    """
    Resolve a JoySafeterAuthContext for the current request.

    Authentication is tried in order:
    1. X-Api-Key header  -> JoySafeterApiKey lookup (DB)
    2. JWT claims        -> decode token, 0 DB queries
    """

    # ------------------------------------------------------------------
    # 1. Try X-Api-Key header
    # ------------------------------------------------------------------
    api_key_header = request.headers.get("X-Api-Key")
    if api_key_header:
        ctx = await _auth_via_api_key(api_key_header, db)
        if ctx is not None:
            return ctx
        raise AuthenticationError(
            "API Key 无效或已过期 / Invalid or expired API key",
            code="INVALID_API_KEY",
        )

    # ------------------------------------------------------------------
    # 2. JWT claims + real-time membership/project verification
    # ------------------------------------------------------------------
    ctx = await _auth_via_jwt_claims(request, db)
    if ctx is not None:
        return ctx

    raise AuthenticationError(
        "凭证缺失或无效，请重新登录 / Missing or invalid credentials",
        code="JOYSAFETER_UNAUTHORIZED",
    )


# ---------------------------------------------------------------------------
# JWT claims fast path (0 DB queries)
# ---------------------------------------------------------------------------


async def _auth_via_jwt_claims(request: Request, db: AsyncSession) -> JoySafeterAuthContext | None:
    """Resolve auth context from JWT claims after verifying DB state.

    Returns None when the request does not contain a complete access JWT.
    """
    from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
    from app.joysafeter_shared.security import decode_token

    # Extract token from Authorization header or cookie
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = extract_token_from_cookies(request.cookies)
    if not token:
        return None

    payload = decode_token(token)
    if not payload or payload.type != "access":
        return None

    # Only use fast path if JWT carries all required claims
    if not payload.org_id or not payload.project_id or not payload.role:
        return None

    target_org_id = str(payload.org_id)
    target_project_id = str(payload.project_id)
    preferred_org_id = request.headers.get("X-Org-Id")
    preferred_project_id = request.headers.get("X-Project-Id")

    if preferred_org_id:
        target_org_id = preferred_org_id
    if preferred_project_id:
        target_project_id = preferred_project_id
    elif target_org_id != str(payload.org_id):
        target_project_id = await _resolve_default_project_id(db, target_org_id, user_id=str(payload.sub))

    return await _verify_joysafeter_context(
        db,
        user_id=str(payload.sub),
        org_id=target_org_id,
        project_id=target_project_id,
        allow_archived_project=True,
    )


async def _resolve_default_project_id(db: AsyncSession, org_id: str, *, user_id: str) -> str:
    """Resolve a usable project when the request switches org via header."""
    member_result = await db.execute(
        select(Member)
        .where(
            Member.user_id == user_id,
            Member.organization_id == org_id,
        )
        .limit(1)
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise AuthenticationError(
            "User is not a member of the requested organization",
            code="NOT_ORG_MEMBER",
        )

    projects = await ProjectService(db).list_accessible_projects(
        org_id=org_id,
        user_id=user_id,
        org_role=_map_org_role(member.role),
    )
    default_project = next((project for project in projects if project.is_default), None)
    if default_project is None and projects:
        default_project = projects[0]
    if default_project is not None:
        return default_project.id

    raise AuthenticationError(
        "No project found for organization",
        code="NO_PROJECT",
    )


async def _verify_joysafeter_context(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    project_id: str,
    allow_archived_project: bool,
) -> JoySafeterAuthContext:
    """Verify current org membership and project ownership against the DB."""
    result = await db.execute(
        select(Member)
        .where(
            Member.user_id == user_id,
            Member.organization_id == org_id,
        )
        .limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise AuthenticationError(
            "组织成员资格已失效，请重新登录 / Organization membership expired, please re-login",
            code="MEMBERSHIP_EXPIRED",
        )

    role = _map_org_role(member.role)
    project_service = ProjectService(db)
    project = await project_service.get_accessible_project(
        project_id=project_id,
        org_id=org_id,
        user_id=user_id,
        org_role=role,
        allow_archived=True,
    )
    if not project:
        raise AuthenticationError(
            "Project not found or access denied",
            code="PROJECT_ACCESS_DENIED",
        )
    if project.archived_at is not None and not allow_archived_project:
        raise ResourceConflictError(
            "项目已归档，仅支持只读操作 / Project is archived and read-only",
            code="PROJECT_ARCHIVED",
            user_action="refresh",
        )

    project_role = await project_service.get_project_member_role(project_id, user_id)
    is_super_user = await _is_platform_super_user(db, user_id)
    return JoySafeterAuthContext(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        role=role,
        project_role=project_role,
        is_super_user=is_super_user,
    )


async def _is_platform_super_user(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(select(AuthUser.is_super_user).where(AuthUser.id == user_id).limit(1))
    return bool(result.scalar_one_or_none())


# ---------------------------------------------------------------------------
# API key auth path
# ---------------------------------------------------------------------------


async def _auth_via_api_key(
    raw_key: str,
    db: AsyncSession,
) -> JoySafeterAuthContext | None:
    """Authenticate via a raw API key in the X-Api-Key header."""

    key_hash = _hash_api_key(raw_key)

    result = await db.execute(select(JoySafeterApiKey).where(JoySafeterApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None

    # Check revocation
    if api_key.revoked_at is not None:
        return None

    # Check expiration
    now = datetime.now(timezone.utc)
    if api_key.expires_at is not None and api_key.expires_at < now:
        return None

    # The key delegates its creator's authority, so it is only valid while the
    # creator still has access to the key's project. Verify that on every request
    # (the read path never re-verifies context otherwise), WITHOUT rebuilding the
    # context from the creator — the key stays capped at its own stored role. A
    # removed or project-revoked creator makes the key stop authenticating.
    creator_member = (
        await db.execute(
            select(Member)
            .where(Member.user_id == api_key.created_by, Member.organization_id == api_key.org_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    creator_has_access = creator_member is not None and (
        await ProjectService(db).get_accessible_project(
            project_id=api_key.project_id,
            org_id=api_key.org_id,
            user_id=api_key.created_by,
            org_role=JoySafeterRole.normalize(creator_member.role),
            allow_archived=True,
        )
        is not None
    )
    if not creator_has_access:
        raise AccessDeniedError(
            "API key creator no longer has access to the project",
            code="AUTH_API_KEY_ACCESS_REVOKED",
        )

    # Best-effort update last_used_at (non-blocking; failures are swallowed)
    try:
        api_key.last_used_at = now
        await db.commit()
    except Exception:
        logger.debug("Failed to update last_used_at for API key", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass

    # A project-scoped API key is NOT an org super-user: its stored role is the
    # key's capability WITHIN its own project. Carry it as project_role and keep
    # the org role at the non-super-user baseline so effective_project_capability
    # scopes it to this project only.
    return JoySafeterAuthContext(
        user_id=api_key.created_by,
        org_id=api_key.org_id,
        project_id=api_key.project_id,
        role=JoySafeterRole.MEMBER,
        principal_type="api_key",
        project_role=api_key.role,
        is_super_user=False,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper dependencies
# ---------------------------------------------------------------------------


async def require_joysafeter_write(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require at least write-level access.

    Performs a real-time DB check to verify the user still has membership
    and the project still belongs to their org. This prevents stale JWT
    claims from authorizing writes after the user has been removed.
    """
    return await _require_write_context(db, ctx)


async def require_joysafeter_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require admin-level access (owner / admin — can manage members).

    Always verifies against DB for sensitive operations.
    """
    return await _require_admin_context(db, ctx)


async def require_joysafeter_read(
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require at least read access (any authenticated role including viewer)."""
    return ctx


def _require_user_principal(ctx: JoySafeterAuthContext) -> JoySafeterAuthContext:
    if ctx.principal_type != "user":
        raise AccessDeniedError(
            "User session required",
            code="JOYSAFETER_USER_SESSION_REQUIRED",
        )
    return ctx


async def _require_write_context(db: AsyncSession, ctx: JoySafeterAuthContext) -> JoySafeterAuthContext:
    verified = await _verify_joysafeter_context(
        db,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        project_id=ctx.project_id,
        allow_archived_project=False,
    )
    creator_capability = effective_project_capability(verified.role, verified.project_role)

    if ctx.principal_type == "api_key":
        # A service key must never exceed the capability it was minted with, even
        # if its creator is (or has since become) an org super-user. The re-verify
        # above still runs so a removed/downgraded creator revokes the key's write
        # access, but the effective capability is capped at min(key, creator) and
        # the returned context keeps the key's own (non-super-user) identity so
        # downstream quota accounting still treats it as a service principal.
        key_capability = effective_project_capability(JoySafeterRole.MEMBER, ctx.project_role)
        if min(creator_capability, key_capability) < ProjectCapability.WRITE:
            raise AccessDeniedError(
                "Write access required",
                code="JOYSAFETER_WRITE_REQUIRED",
            )
        return ctx

    if creator_capability < ProjectCapability.WRITE:
        raise AccessDeniedError(
            "Write access required",
            code="JOYSAFETER_WRITE_REQUIRED",
        )

    return verified


async def _require_admin_context(db: AsyncSession, ctx: JoySafeterAuthContext) -> JoySafeterAuthContext:
    if not ctx.role.can_manage_members():
        raise AccessDeniedError(
            "Admin access required",
            code="JOYSAFETER_ADMIN_REQUIRED",
        )

    ctx = await _verify_joysafeter_context(
        db,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        project_id=ctx.project_id,
        allow_archived_project=True,
    )
    if not ctx.role.can_manage_members():
        raise AccessDeniedError(
            "Admin access required",
            code="JOYSAFETER_ADMIN_REQUIRED",
        )

    return ctx


async def require_joysafeter_user_context(
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require a browser/user principal rather than a project-scoped API key."""
    return _require_user_principal(ctx)


async def require_joysafeter_user_write(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require a user principal with write access to the active project."""
    ctx = _require_user_principal(ctx)
    return await _require_write_context(db, ctx)


async def require_joysafeter_user_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require a user principal with organization admin privileges."""
    ctx = _require_user_principal(ctx)
    return await _require_admin_context(db, ctx)


async def require_joysafeter_platform_admin(
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require a platform super-user for infrastructure-level operations."""
    ctx = _require_user_principal(ctx)
    if not ctx.is_super_user:
        raise AccessDeniedError(
            "Platform admin access required",
            code="JOYSAFETER_PLATFORM_ADMIN_REQUIRED",
        )
    return ctx


async def require_joysafeter_project_admin(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require the caller to be admin OF THE PATH ``project_id`` (org super-users
    included).

    Declarative counterpart of the inline project-admin check that guards project
    -member management. Scoped to the path project (not the caller's active-context
    project), so a project admin manages members of exactly the project they
    administer. Being a dependency, a new member-management route cannot silently
    ship with only a read-level guard.
    """
    ctx = _require_user_principal(ctx)
    actor_role = await ProjectService(db).get_project_member_role(project_id, ctx.user_id)
    if effective_project_capability(ctx.role, actor_role) < ProjectCapability.ADMIN:
        raise AccessDeniedError(
            "Project admin access required",
            code="JOYSAFETER_PROJECT_ADMIN_REQUIRED",
        )
    return ctx
