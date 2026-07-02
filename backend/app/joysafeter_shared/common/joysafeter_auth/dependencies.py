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
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.app_errors import AccessDeniedError, AuthenticationError
from app.joysafeter_shared.common.dependencies import get_current_user
from app.joysafeter_shared.database import get_db

from .context import JoySafeterAuthContext, JoySafeterRole

# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# Map OrgRole string values (from the member table) to JoySafeterRole.
# OrgRole has: owner, admin, member.  "member" maps to "developer" in joysafeter.
def _map_org_role(role_value: str) -> JoySafeterRole:
    """Convert an OrgRole string to a JoySafeterRole, defaulting to VIEWER."""
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

    # ------------------------------------------------------------------
    # 3. Cookie/session fallback (for browser login, issues new-style token)
    # ------------------------------------------------------------------
    try:
        ctx = await _auth_via_user_session(request, db)
        if ctx is not None:
            return ctx
    except AuthenticationError:
        raise
    except Exception as exc:
        logger.error(f"JoySafeter auth session error: {exc}", exc_info=True)

    raise AuthenticationError(
        "凭证缺失或无效，请重新登录 / Missing or invalid credentials",
        code="JOYSAFETER_UNAUTHORIZED",
    )


# ---------------------------------------------------------------------------
# JWT claims fast path (0 DB queries)
# ---------------------------------------------------------------------------


async def _auth_via_jwt_claims(request: Request, db: AsyncSession) -> JoySafeterAuthContext | None:
    """Resolve auth context from JWT claims after verifying DB state.

    Returns None if the token doesn't carry org/project claims (old tokens).
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
        target_project_id = await _resolve_default_project_id(db, target_org_id)

    return await _verify_joysafeter_context(
        db,
        user_id=str(payload.sub),
        org_id=target_org_id,
        project_id=target_project_id,
        allow_archived_project=True,
    )


async def _resolve_default_project_id(db: AsyncSession, org_id: str) -> str:
    """Resolve a usable project when the request switches org via header."""
    result = await db.execute(
        select(Project).where(
            Project.org_id == org_id,
            Project.is_default.is_(True),
            Project.archived_at.is_(None),
        ).limit(1)
    )
    project = result.scalar_one_or_none()
    if project:
        return project.id

    result = await db.execute(
        select(Project).where(
            Project.org_id == org_id,
            Project.archived_at.is_(None),
        ).limit(1)
    )
    project = result.scalar_one_or_none()
    if project:
        return project.id

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
        select(Member).where(
            Member.user_id == user_id,
            Member.organization_id == org_id,
        ).limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise AuthenticationError(
            "组织成员资格已失效，请重新登录 / Organization membership expired, please re-login",
            code="MEMBERSHIP_EXPIRED",
        )

    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.org_id == org_id,
        ).limit(1)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise AuthenticationError(
            "Project not found or access denied",
            code="PROJECT_ACCESS_DENIED",
        )
    if project.archived_at is not None and not allow_archived_project:
        raise AccessDeniedError(
            "项目已归档，仅支持只读操作 / Project is archived and read-only",
            code="PROJECT_ARCHIVED",
        )

    return JoySafeterAuthContext(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        role=_map_org_role(member.role),
    )


# ---------------------------------------------------------------------------
# API key auth path
# ---------------------------------------------------------------------------


async def _auth_via_api_key(
    raw_key: str,
    db: AsyncSession,
) -> JoySafeterAuthContext | None:
    """Authenticate via a raw API key in the X-Api-Key header."""

    key_hash = _hash_api_key(raw_key)

    result = await db.execute(
        select(JoySafeterApiKey).where(JoySafeterApiKey.key_hash == key_hash)
    )
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

    role = JoySafeterRole.normalize(api_key.role)

    return JoySafeterAuthContext(
        user_id=api_key.created_by,
        org_id=api_key.org_id,
        project_id=api_key.project_id,
        role=role,
    )


# ---------------------------------------------------------------------------
# Cookie / Bearer auth path
# ---------------------------------------------------------------------------


async def _auth_via_user_session(
    request: Request,
    db: AsyncSession,
) -> JoySafeterAuthContext | None:
    """Authenticate via the existing user session (cookie/Bearer)."""
    from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies

    # Extract token from Authorization header or cookie (same as v1 auth)
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        token = extract_token_from_cookies(request.cookies)

    logger.info(f"[JoySafeterAuth] token extracted: {bool(token)}, cookies present: {list(request.cookies.keys())}")

    if not token:
        raise AuthenticationError("Missing credentials", code="MISSING_CREDENTIALS")

    user = await get_current_user(token=token, request=request, db=db)
    logger.info(f"[JoySafeterAuth] user resolved: {user.id}")

    # Look up the user's org membership.
    # Prefer X-Org-Id header if provided (org switching), otherwise first found.
    preferred_org_id = request.headers.get("X-Org-Id")
    if preferred_org_id:
        result = await db.execute(
            select(Member).where(
                Member.user_id == user.id,
                Member.organization_id == preferred_org_id,
            ).limit(1)
        )
    else:
        result = await db.execute(
            select(Member).where(Member.user_id == user.id).limit(1)
        )
    membership = result.scalar_one_or_none()
    if membership is None and preferred_org_id:
        # User explicitly requested an org they don't belong to
        raise AuthenticationError(
            "User is not a member of the requested organization",
            code="NOT_ORG_MEMBER",
        )
    if membership is None:
        # Auto-create a default organization and project for the user
        import uuid as _uuid

        from app.joysafeter_domain.models.joysafeter_organization import Organization

        org_id = str(_uuid.uuid4())
        org = Organization(id=org_id, name=user.name or "Default", slug="default")
        db.add(org)
        membership = Member(
            id=str(_uuid.uuid4()),
            user_id=user.id,
            organization_id=org_id,
            role="owner",
        )
        db.add(membership)
        default_project = Project(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db.add(default_project)
        await db.commit()
        await db.refresh(membership)

    org_id = membership.organization_id
    role = _map_org_role(membership.role)

    # Resolve project_id: prefer explicit header, otherwise default project.
    project_id = request.headers.get("X-Project-Id")
    if project_id:
        # SECURITY: Verify the project belongs to the user's organization
        proj_result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.org_id == org_id,
            ).limit(1)
        )
        verified_project = proj_result.scalar_one_or_none()
        if not verified_project:
            project_id = None
        elif verified_project.archived_at is not None:
            project_id = None

    if not project_id:
        proj_result = await db.execute(
            select(Project).where(
                Project.org_id == org_id,
                Project.is_default.is_(True),
            ).limit(1)
        )
        default_project = proj_result.scalar_one_or_none()
        if default_project is None:
            # Fall back to *any* project in the org
            proj_result = await db.execute(
                select(Project).where(Project.org_id == org_id).limit(1)
            )
            default_project = proj_result.scalar_one_or_none()
        if default_project is None:
            raise AuthenticationError(
                "No project found for organization",
                code="NO_PROJECT",
            )
        project_id = default_project.id

    return JoySafeterAuthContext(
        user_id=user.id,
        org_id=org_id,
        project_id=project_id,
        role=role,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper dependencies
# ---------------------------------------------------------------------------


async def require_joysafeter_write(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require at least write-level access (owner / admin / developer).

    Performs a real-time DB check to verify the user still has membership
    and the project still belongs to their org. This prevents stale JWT
    claims from authorizing writes after the user has been removed.
    """
    if not ctx.role.can_write():
        raise AccessDeniedError(
            "Write access required",
            code="JOYSAFETER_WRITE_REQUIRED",
        )

    ctx = await _verify_joysafeter_context(
        db,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        project_id=ctx.project_id,
        allow_archived_project=False,
    )
    if not ctx.role.can_write():
        raise AccessDeniedError(
            "Write access required",
            code="JOYSAFETER_WRITE_REQUIRED",
        )

    return ctx


async def require_joysafeter_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require admin-level access (owner / admin — can manage members).

    Always verifies against DB for sensitive operations.
    """
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


async def require_joysafeter_read(
    ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> JoySafeterAuthContext:
    """Require at least read access (any authenticated role including viewer)."""
    return ctx
