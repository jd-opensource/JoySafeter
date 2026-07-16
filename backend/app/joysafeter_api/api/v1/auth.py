"""
JoySafeter auth routes — /auth endpoints.

Covers two surfaces under a single `/api/v1/auth` prefix:

  - Identity flow (sign-in / sign-up / refresh / forgot-password /
    reset-password / verify-email / logout / session / ws-token).
    Ported from the retired ``api/v1/auth.py`` so the frontend can call
    everything under ``MANAGED_API_BASE`` and v1 can be deleted.

  - Managed user context (/me, /switch-context, /projects, /api-keys,
    /members, /organizations, ...) — assumes the user is already signed
    in via the identity flow above.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, cast

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_api.services import ApiKeyService, AuthService, AuthSessionService, ProjectService
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru
from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    get_joysafeter_auth_context,
    require_joysafeter_admin,
    require_joysafeter_write,
)
from app.joysafeter_shared.common.response import success_response
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.rate_limit import auth_rate_limit, strict_rate_limit
from app.joysafeter_shared.security import Token, create_access_token, decode_token

router = APIRouter(tags=["joysafeter-auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuthMeResponse(BaseModel):
    user_id: str
    org_id: str
    project_id: str
    role: str
    org_name: Optional[str] = None
    project_name: Optional[str] = None


class SwitchContextRequest(BaseModel):
    org_id: Optional[str] = None
    project_id: Optional[str] = None


class SwitchContextResponse(BaseModel):
    user_id: str
    org_id: str
    project_id: str
    role: str


class ProjectResponse(BaseModel):
    id: str
    org_id: str
    name: str
    slug: str
    is_default: bool
    archived_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CreateProjectRequest(BaseModel):
    name: str
    slug: str


class ApiKeyResponse(BaseModel):
    id: str
    project_id: str
    name: str
    key_prefix: str
    role: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ApiKeyCreateResponse(BaseModel):
    """Response for API key creation — includes the raw key (shown only once)."""

    id: str
    project_id: str
    name: str
    key_prefix: str
    role: str
    raw_key: str


class CreateApiKeyRequest(BaseModel):
    name: str
    role: str = "developer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        slug=project.slug,
        is_default=project.is_default,
        archived_at=str(project.archived_at) if project.archived_at else None,
        created_at=str(project.created_at) if project.created_at else None,
        updated_at=str(project.updated_at) if project.updated_at else None,
    )


def _project_context_payload(project: Project) -> dict[str, object]:
    return {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "slug": project.slug,
        "is_default": project.is_default,
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
    }


def _api_key_to_response(key) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        project_id=key.project_id,
        name=key.name,
        key_prefix=key.key_prefix,
        role=key.role,
        created_at=str(key.created_at) if key.created_at else None,
        last_used_at=str(key.last_used_at) if key.last_used_at else None,
    )


def _auth_permission_error(
    *,
    code: str,
    message: str,
    organization_id: str | None = None,
    actor_role: str | None = None,
    target_role: str | None = None,
    current_role: str | None = None,
) -> AppError:
    data: dict[str, object] = {}
    if organization_id is not None:
        data["organization_id"] = organization_id
    if actor_role is not None:
        data["actor_role"] = actor_role
    if target_role is not None:
        data["target_role"] = target_role
    if current_role is not None:
        data["current_role"] = current_role
    return AccessDeniedError(
        code=code,
        message=message,
        data=data,
        source="auth",
        user_action="request_access",
    )


def _normalize_assignable_role(role: str) -> JoySafeterRole:
    normalized = (role or "").strip().lower()
    if normalized == "member":
        normalized = "developer"
    allowed = [JoySafeterRole.ADMIN.value, JoySafeterRole.DEVELOPER.value, JoySafeterRole.VIEWER.value]
    if normalized not in set(allowed):
        raise InvalidRequestError(
            code="AUTH_INVALID_ASSIGNABLE_ROLE",
            message="Invalid role. Must be one of: admin, developer, viewer",
            data={"role": role, "allowed": allowed},
            source="auth",
            user_action="correct_request",
        )
    return JoySafeterRole(normalized)


def _ensure_can_assign_role(actor_role: JoySafeterRole, target_role: JoySafeterRole) -> None:
    if not actor_role.can_grant(target_role):
        raise _auth_permission_error(
            code="AUTH_ROLE_GRANT_FORBIDDEN",
            message="Cannot grant a role higher than your own",
            actor_role=actor_role.value,
            target_role=target_role.value,
        )


def _ensure_can_modify_member(actor_role: JoySafeterRole, current_role: str, new_role: JoySafeterRole) -> None:
    current = JoySafeterRole.normalize(current_role)
    if current == JoySafeterRole.OWNER:
        raise _auth_permission_error(
            code="AUTH_OWNER_ROLE_CHANGE_FORBIDDEN",
            message="Cannot change the owner's role",
            actor_role=actor_role.value,
            current_role=current.value,
            target_role=new_role.value,
        )
    if not actor_role.can_grant(current) or not actor_role.can_grant(new_role):
        raise _auth_permission_error(
            code="AUTH_ROLE_MODIFY_FORBIDDEN",
            message="Cannot modify or grant a role higher than your own",
            actor_role=actor_role.value,
            current_role=current.value,
            target_role=new_role.value,
        )


# ---------------------------------------------------------------------------
# Identity flow — ported from v1/auth.py
#
# These endpoints power the unauthenticated / pre-context login surface:
# sign-up, sign-in, refresh, password reset, email verification, logout,
# session lookup, ws-token. They don't depend on JoySafeterAuthContext
# (some explicitly *return* the credentials a context would be built from)
# so they live alongside the managed-context endpoints but don't require
# them as a dependency.
# ---------------------------------------------------------------------------


SameSiteType = Literal["lax", "strict", "none"]


def _get_samesite_value(value: str) -> Optional[SameSiteType]:
    """Convert string to SameSite literal type for cookie operations."""
    normalized = value.lower().strip()
    if normalized in ("lax", "strict", "none"):
        return cast(SameSiteType, normalized)
    return None


def _set_auth_cookies(response: Response, result: dict) -> None:
    """Write auth cookies from a login/refresh result."""
    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token")
    csrf_token = result.get("csrf_token")
    expires_in = result.get("expires_in", settings.cookie_max_age)

    if access_token:
        response.set_cookie(
            key=settings.cookie_name,
            value=access_token,
            max_age=expires_in,
            httponly=True,
            secure=settings.cookie_secure_effective,
            samesite=_get_samesite_value(settings.cookie_samesite),
            domain=settings.cookie_domain,
            path="/",
        )

    if refresh_token:
        refresh_expires = settings.refresh_token_expire_days * 24 * 60 * 60
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=refresh_expires,
            httponly=True,
            secure=settings.cookie_secure_effective,
            samesite=_get_samesite_value(settings.cookie_samesite),
            domain=settings.cookie_domain,
            path="/",
        )

    if csrf_token:
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            max_age=expires_in,
            httponly=False,
            secure=settings.cookie_secure_effective,
            samesite=_get_samesite_value(settings.cookie_samesite),
            domain=settings.cookie_domain,
            path="/",
        )


# --- Identity-flow schemas --------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=100)
    image: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=100)


class ResetPasswordForCurrentUserRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    image: Optional[str]
    email_verified: bool
    is_super_user: bool


# --- Identity-flow helpers --------------------------------------------------


def _extract_bearer(auth_header: Optional[str]) -> str:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token", code="BEARER_TOKEN_MISSING")
    return auth_header.split(" ", 1)[1]


def _has_auth_credentials(request: Request, auth_header: Optional[str]) -> bool:
    if auth_header:
        return True
    if request.cookies.get("refresh_token"):
        return True
    try:
        return bool(extract_token_from_cookies(request.cookies))
    except Exception:
        logger.debug("Failed to inspect auth cookies", exc_info=True)
        return False


async def _get_current_auth_user(
    auth_header: Optional[str], db: AsyncSession, request: Optional[Request] = None
) -> AuthUser:
    """Validate and return AuthUser from Bearer token or Cookie."""
    token = None

    if auth_header:
        try:
            token = _extract_bearer(auth_header)
        except AuthenticationError:
            logger.debug("Failed to extract bearer token from Authorization header", exc_info=True)

    if not token and request:
        try:
            token = extract_token_from_cookies(request.cookies)
        except Exception:
            logger.debug("Failed to read token from cookies", exc_info=True)

    if not token:
        raise AuthenticationError("Missing credentials", code="MISSING_CREDENTIALS")

    user_service = AuthService(db)

    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        user = await user_service.get_user_by_id(str(user_id))
        if user and user.is_active:
            return user
        raise AuthenticationError("User not found or inactive", code="USER_INVALID")

    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        user = await user_service.user_repo.get(uuid.UUID(session.user_id))
        if user and user.is_active:
            return user
        raise AuthenticationError("User not found or inactive", code="USER_INVALID")

    raise AuthenticationError("Invalid or expired token", code="TOKEN_INVALID")


def _user_to_response(user: AuthUser) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        image=user.image,
        email_verified=user.email_verified,
        is_super_user=user.is_super_user,
    )


# --- Identity-flow endpoints ------------------------------------------------


@router.post("/sign-up/email")
@auth_rate_limit()
async def sign_up_with_email(
    http_request: Request,
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Email registration endpoint."""
    service = AuthService(db)
    data = await service.register(
        email=body.email,
        name=body.name,
        password=body.password,
        image=body.image,
        is_super_user=False,
    )

    # Do not auto-login after signup; no Cookie is set. User must sign in manually.
    user_data = data.get("user", {})
    return success_response(
        data={"user": user_data},
        message="Registration successful. Please sign in to continue.",
    )


@router.post("/sign-in/email")
@auth_rate_limit()
async def sign_in_with_email(
    http_request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Email login endpoint."""
    service = AuthService(db)
    result = await service.login(email=body.email, password=body.password)
    _set_auth_cookies(response, result)
    return success_response(data=result, message="Login successful")


@router.post("/login/form", response_model=Token)
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Login via OAuth2 password form (for Swagger UI compatibility)."""
    service = AuthService(db)
    result = await service.login(email=form_data.username, password=form_data.password)
    return Token(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    token: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    """Logout current user by invalidating tokens and clearing cookies."""
    try:
        service = AuthService(db)
        refresh_token = request.cookies.get("refresh_token")

        user_id = None
        try:
            current_user = await _get_current_auth_user(token, db, request)
            user_id = current_user.id
        except AppError:
            logger.debug("Failed to resolve current user during logout", exc_info=True)

        if refresh_token and user_id:
            try:
                await service._delete_refresh_token(refresh_token, user_id)
            except Exception:
                logger.debug("Failed to delete refresh token during logout", exc_info=True)

        response.delete_cookie(
            key=settings.cookie_name,
            domain=settings.cookie_domain,
            path="/",
            samesite=_get_samesite_value(settings.cookie_samesite),
        )
        response.delete_cookie(
            key="refresh_token",
            domain=settings.cookie_domain,
            path="/",
            samesite=_get_samesite_value(settings.cookie_samesite),
        )
        response.delete_cookie(
            key="csrf_token",
            domain=settings.cookie_domain,
            path="/",
            samesite=_get_samesite_value(settings.cookie_samesite),
        )

        return success_response(message="Logout successful")

    except Exception:
        logger.debug("Failed to perform full logout, clearing cookies anyway", exc_info=True)
        response.delete_cookie(key=settings.cookie_name, domain=settings.cookie_domain, path="/")
        response.delete_cookie(key="refresh_token", domain=settings.cookie_domain, path="/")
        response.delete_cookie(key="csrf_token", domain=settings.cookie_domain, path="/")
        return success_response(message="Logout successful")


@router.post("/forgot-password")
@strict_rate_limit()
async def forgot_password(
    http_request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset email (silent even if email is unknown)."""
    service = AuthService(db)
    await service.request_password_reset(body.email)
    return success_response(message="If your email is registered, you will receive a password reset link shortly.")


@router.post("/reset-password")
@strict_rate_limit()
async def reset_password(
    http_request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using a one-time token."""
    service = AuthService(db)
    await service.reset_password(
        token=body.token,
        new_password=body.new_password,
    )
    return success_response(message="Password reset successful")


@router.post("/me/reset-password")
async def reset_password_for_current_user(
    http_request: Request,
    body: ResetPasswordForCurrentUserRequest,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Reset password for the current logged-in user (no old password required)."""
    current_user = await _get_current_auth_user(token, db, http_request)
    service = AuthService(db)
    await service.reset_password_for_current_user(
        user=current_user,
        new_password=body.new_password,
    )
    return success_response(message="Password reset successful")


# Backwards-compat alias: the frontend calls `auth/me/change-password` for
# the "change my own password" flow. There's no separate change-password
# endpoint on the server; we route it to the same reset-for-current-user
# handler so it accepts the same payload shape.
@router.post("/me/change-password")
async def change_password_for_current_user(
    http_request: Request,
    body: ResetPasswordForCurrentUserRequest,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Alias for /me/reset-password — used by the frontend's `change password` UI."""
    return await reset_password_for_current_user(
        http_request=http_request,
        body=body,
        db=db,
        token=token,
    )


@router.post("/verify-email")
async def verify_email(
    token: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Verify email ownership using the provided token."""
    service = AuthService(db)
    await service.verify_email(token)
    return success_response(message="Email verified successfully")


@router.post("/resend-verification")
async def resend_verification(
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Resend a verification email to the current user."""
    current_user = await _get_current_auth_user(token, db)
    service = AuthService(db)
    await service.resend_verification_email(current_user)
    return success_response(message="Verification email sent")


@router.get("/session")
async def get_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Get current user session (JWT mode: returns user info from token)."""
    try:
        current_user = await _get_current_auth_user(token, db, request)
        return success_response(data={"user": _user_to_response(current_user)})
    except AppError:
        if _has_auth_credentials(request, token):
            raise
        # Return null user only when no auth credential was provided.
        return success_response(data={"user": None})


@router.get("/ws-token")
async def get_ws_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Return a short-lived token for WebSocket authentication (60 s)."""
    current_user = await _get_current_auth_user(token, db, request)
    ws_token = create_access_token(str(current_user.id), expires_delta=timedelta(seconds=60))
    return success_response(data={"token": ws_token})


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Refresh access token using refresh token from Cookie or Authorization header."""

    service = AuthService(db)

    # Try to read refresh token from Cookie
    refresh_token_value = None
    try:
        refresh_token_value = request.cookies.get("refresh_token")
    except Exception:
        logger.debug("Failed to read refresh_token from cookies", exc_info=True)

    if not refresh_token_value and token:
        try:
            bearer_token = token.replace("Bearer ", "") if token.startswith("Bearer ") else token
            payload = decode_token(bearer_token)
            if payload and getattr(payload, "type", None) == "refresh":
                user_id = payload.sub
                user = await service.get_user_by_id(str(user_id))
                if user and user.is_active:
                    (
                        access_token,
                        new_refresh_token,
                        csrf_token,
                        access_expires,
                        refresh_expires,
                    ) = await service._issue_jwt_tokens(user.id)
                    result = {
                        "access_token": access_token,
                        "refresh_token": new_refresh_token,
                        "csrf_token": csrf_token,
                        "token_type": "bearer",
                        "expires_in": int((access_expires - datetime.now(timezone.utc)).total_seconds()),
                    }
                    _set_auth_cookies(response, result)
                    return success_response(
                        data={
                            "access_token": result["access_token"],
                            "csrf_token": result["csrf_token"],
                            "token_type": result["token_type"],
                            "expires_in": result["expires_in"],
                        }
                    )
        except Exception:
            logger.debug("Failed to refresh token via Authorization header", exc_info=True)

    if refresh_token_value:
        try:
            result = await service.refresh_token(refresh_token_value)
            _set_auth_cookies(response, result)
            return success_response(
                data={
                    "access_token": result["access_token"],
                    "csrf_token": result["csrf_token"],
                    "token_type": result["token_type"],
                    "expires_in": result["expires_in"],
                }
            )
        except Exception:
            logger.debug("Failed to refresh token via cookie refresh_token", exc_info=True)

    raise AuthenticationError("Invalid or expired refresh token", code="REFRESH_TOKEN_INVALID")


# ---------------------------------------------------------------------------
# Managed-context endpoints (assume user is already signed in via the
# identity flow above; depend on JoySafeterAuthContext).
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Return current user + org + project info in the format expected by the frontend."""
    # Look up user
    user_result = await db.execute(select(AuthUser).where(AuthUser.id == auth_ctx.user_id).limit(1))
    user = user_result.scalar_one_or_none()

    # Look up current org
    org_result = await db.execute(select(Organization).where(Organization.id == auth_ctx.org_id).limit(1))
    org = org_result.scalar_one_or_none()

    # Look up current project
    proj_result = await db.execute(select(Project).where(Project.id == auth_ctx.project_id).limit(1))
    proj = proj_result.scalar_one_or_none()

    # List all orgs user belongs to
    all_members_result = await db.execute(
        select(Member, Organization)
        .join(Organization, Member.organization_id == Organization.id)
        .where(Member.user_id == auth_ctx.user_id)
    )
    all_memberships = all_members_result.all()
    organizations = [
        {
            "id": o.id,
            "name": o.name,
            "slug": o.slug,
            "role": m.role,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for m, o in all_memberships
    ]

    # List all projects in current org
    all_projects_result = await db.execute(
        select(Project).where(Project.org_id == auth_ctx.org_id, Project.archived_at.is_(None))
    )
    all_projects = all_projects_result.scalars().all()
    projects = [_project_context_payload(p) for p in all_projects]

    return {
        "user": {
            "id": user.id if user else auth_ctx.user_id,
            "email": user.email if user else "",
            "name": user.name if user else "",
        },
        "organization": {
            "id": org.id if org else auth_ctx.org_id,
            "name": org.name if org else "",
            "slug": org.slug if org else "",
            "role": auth_ctx.role.value,
        },
        "project": _project_context_payload(proj)
        if proj
        else {
            "id": auth_ctx.project_id,
            "org_id": auth_ctx.org_id,
            "name": "",
            "slug": "",
            "is_default": True,
            "archived_at": None,
        },
        "organizations": organizations,
        "projects": projects,
    }


@router.post("/switch-context")
async def switch_context(
    req: SwitchContextRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Switch the user's active org/project context. Validates membership."""
    target_org_id = req.org_id or auth_ctx.org_id

    # Validate user is a member of the target org
    member_result = await db.execute(
        select(Member)
        .where(
            Member.user_id == auth_ctx.user_id,
            Member.organization_id == target_org_id,
        )
        .limit(1)
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise _auth_permission_error(
            code="AUTH_ORGANIZATION_MEMBERSHIP_REQUIRED",
            message="User is not a member of the target organization",
            organization_id=target_org_id,
        )

    # Resolve project
    target_project_id = req.project_id
    if not target_project_id:
        default_proj_result = await db.execute(
            select(Project)
            .where(
                Project.org_id == target_org_id,
                Project.is_default.is_(True),
                Project.archived_at.is_(None),
            )
            .limit(1)
        )
        default_proj = default_proj_result.scalar_one_or_none()
        if not default_proj:
            fallback_project_result = await db.execute(
                select(Project)
                .where(
                    Project.org_id == target_org_id,
                    Project.archived_at.is_(None),
                )
                .order_by(Project.created_at)
                .limit(1)
            )
            default_proj = fallback_project_result.scalar_one_or_none()
        if not default_proj:
            raise NotFoundError(
                code="DEFAULT_PROJECT_NOT_FOUND",
                message="No default project found for the organization",
                data={"organization_id": target_org_id},
                user_action="refresh",
            )
        target_project_id = default_proj.id
    else:
        proj_result = await db.execute(
            select(Project)
            .where(
                Project.id == target_project_id,
                Project.org_id == target_org_id,
            )
            .limit(1)
        )
        proj = proj_result.scalar_one_or_none()
        if not proj:
            raise _project_not_found_error(
                target_project_id,
                organization_id=target_org_id,
                message="Project not found in the target organization",
            )

    # Fetch resolved project details
    proj_result = await db.execute(select(Project).where(Project.id == target_project_id).limit(1))
    resolved_project = proj_result.scalar_one_or_none()

    # List all projects in target org
    all_projects_result = await db.execute(
        select(Project).where(Project.org_id == target_org_id, Project.archived_at.is_(None))
    )
    all_projects = all_projects_result.scalars().all()

    # Issue new JWT with updated org/project context
    from app.joysafeter_shared.security import create_access_token

    new_access_token = create_access_token(
        subject=auth_ctx.user_id,
        org_id=target_org_id,
        project_id=target_project_id,
        role=JoySafeterRole.normalize(member.role).value,
    )

    return {
        "org_id": target_org_id,
        "project_id": target_project_id,
        "access_token": new_access_token,
        "project": _project_context_payload(resolved_project)
        if resolved_project
        else {
            "id": target_project_id,
            "org_id": target_org_id,
            "name": "",
            "slug": "",
            "is_default": False,
            "archived_at": None,
        },
        "projects": [_project_context_payload(p) for p in all_projects],
    }


@router.get("/projects")
async def list_projects(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[ProjectResponse]:
    """List projects for the current org."""
    svc = ProjectService(db)
    projects = await svc.list_projects(auth_ctx.org_id, include_archived=include_archived)
    return [_project_to_response(p) for p in projects]


@router.post("/projects", status_code=201)
async def create_project(
    req: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    """Create a new project (requires admin role)."""
    svc = ProjectService(db)
    project = await svc.create_project(
        org_id=auth_ctx.org_id,
        name=req.name,
        slug=req.slug,
    )
    return _project_to_response(project)


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[ApiKeyResponse]:
    """List API keys for the current project."""
    svc = ApiKeyService(db)
    keys = await svc.list_project_keys(auth_ctx.project_id)
    return [_api_key_to_response(k) for k in keys]


@router.post("/api-keys", status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the raw key once."""
    role = _normalize_assignable_role(req.role)
    _ensure_can_assign_role(auth_ctx.role, role)
    svc = ApiKeyService(db)
    api_key, raw_key = await svc.create_api_key(
        project_id=auth_ctx.project_id,
        org_id=auth_ctx.org_id,
        name=req.name,
        created_by=auth_ctx.user_id,
        role=role.value,
    )
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="api_key.created",
        target_type="api_key",
        target_id=str(api_key.id),
        details={"name": api_key.name, "key_prefix": api_key.key_prefix, "assigned_role": api_key.role},
    )
    return ApiKeyCreateResponse(
        id=str(api_key.id),
        project_id=api_key.project_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        role=api_key.role,
        raw_key=raw_key,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    """Revoke an API key."""
    svc = ApiKeyService(db)
    revoked = await svc.revoke_key(key_id, auth_ctx.project_id)
    if not revoked:
        raise NotFoundError(
            code="API_KEY_NOT_FOUND",
            message="API key not found",
            data={"key_id": str(key_id)},
            user_action="refresh",
        )
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="api_key.revoked",
        target_type="api_key",
        target_id=str(key_id),
    )


# ---------------------------------------------------------------------------
# Project detail routes
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> ProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id))
    project = result.scalar_one_or_none()
    if not project:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return _project_to_response(project)


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    req: UpdateProjectRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id))
    project = result.scalar_one_or_none()
    if not project:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    if project.archived_at is not None:
        raise ResourceConflictError(
            code="PROJECT_ARCHIVED",
            message="Cannot update an archived project",
            data={"project_id": project_id, "organization_id": auth_ctx.org_id},
            user_action="refresh",
        )
    if req.name is not None:
        project.name = req.name
    if req.slug is not None:
        project.slug = req.slug
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project)


async def _cleanup_project_sessions_for_archive(project_id: str, db: AsyncSession) -> None:
    from app.joysafeter_api.runtime_commands import relay_sandbox_destroy_via_redis
    from app.joysafeter_api.services import SandboxService
    from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

    result = await db.execute(
        select(JoySafeterSession.id).where(
            JoySafeterSession.project_id == project_id,
            JoySafeterSession.archived_at.is_(None),
        )
    )
    session_ids = list(result.scalars().all())
    if not session_ids:
        return

    sandbox_svc = SandboxService(db)

    for session_id in session_ids:
        sandbox = await sandbox_svc.find_by_session(session_id)
        if not sandbox or sandbox.status == "destroyed":
            continue

        destroy_relayed = await relay_sandbox_destroy_via_redis(
            sandbox.id,
            reason="project archived",
            boundary="project_api",
            operation="archive_project_destroy_sandbox",
            failure_code="PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
            failure_message="Redis sandbox destroy relay command failed",
            external_id=str(sandbox.external_id or "") or None,
            data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
        )
        if not destroy_relayed:
            raise ServiceUnavailableError(
                code="PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
                message="Failed to destroy project session sandbox runtime.",
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="runtime",
                retryable=True,
                user_action="retry",
            )

        try:
            destroyed = await sandbox_svc.mark_destroyed_cas(sandbox.id, sandbox.status)
            if not destroyed:
                await sandbox_svc.mark_destroyed(sandbox.id)
                destroyed = True
        except Exception as exc:
            log_boundary_failure_loguru(
                logger,
                boundary="project_api",
                code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                message="Failed to mark sandbox destroyed during project archive",
                operation="archive_project_mark_sandbox_destroyed",
                error=exc,
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
            )
            raise ServiceUnavailableError(
                code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                message="Project could not be archived because sandbox state sync failed.",
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
                retryable=True,
                user_action="retry",
            ) from None
        if not destroyed:
            log_boundary_failure_loguru(
                logger,
                boundary="project_api",
                code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                message="Failed to mark sandbox destroyed during project archive",
                operation="archive_project_mark_sandbox_destroyed",
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
            )
            raise ServiceUnavailableError(
                code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                message="Project could not be archived because sandbox state sync failed.",
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
                retryable=True,
                user_action="retry",
            )


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> dict:
    from datetime import datetime, timezone

    result = await db.execute(select(Project).where(Project.id == project_id, Project.org_id == auth_ctx.org_id))
    project = result.scalar_one_or_none()
    if not project:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    if project.is_default:
        raise InvalidRequestError(
            code="PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
            message="Cannot archive the default project",
            data={"project_id": project_id, "organization_id": auth_ctx.org_id},
            user_action="fix_input",
        )

    from app.joysafeter_api.services import JoySafeterTaskService as TaskService

    active_tasks = await TaskService(db).count_active_tasks_for_project(project_id)
    if active_tasks > 0:
        raise ResourceConflictError(
            code="PROJECT_ACTIVE_TASKS",
            message="Project has active tasks. Stop or wait for them before archiving.",
            data={"project_id": project_id, "active": active_tasks},
            retryable=True,
            user_action="retry",
        )
    await _cleanup_project_sessions_for_archive(project_id, db)
    archived_at = datetime.now(timezone.utc)
    from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

    await db.execute(
        update(JoySafeterSession)
        .where(
            JoySafeterSession.project_id == project_id,
            JoySafeterSession.archived_at.is_(None),
        )
        .values(archived_at=archived_at, status="terminated")
    )
    from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService

    await JoySafeterScheduleService(db).pause_for_project_archive(project_id)
    project.archived_at = archived_at
    await db.commit()
    return {"status": "archived"}


@router.post("/projects/{project_id}/set-default")
async def set_default_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    try:
        project = await ProjectService(db).set_default_project(project_id, auth_ctx.org_id)
    except ValueError:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return _project_to_response(project)


@router.post("/projects/{project_id}/restore")
async def restore_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> ProjectResponse:
    try:
        project = await ProjectService(db).restore_project(project_id, auth_ctx.org_id)
    except ValueError:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return _project_to_response(project)


# ---------------------------------------------------------------------------
# User search (for member invite)
# ---------------------------------------------------------------------------


@router.get("/search-users")
async def search_users(
    q: str = Query("", min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
):
    """Search users by email or name for member invitation."""
    from sqlalchemy import or_

    search = f"%{q}%"
    result = await db.execute(
        select(AuthUser)
        .where(
            or_(
                AuthUser.email.ilike(search),
                AuthUser.name.ilike(search),
            )
        )
        .limit(limit)
    )
    users = result.scalars().all()

    existing_result = await db.execute(select(Member.user_id).where(Member.organization_id == auth_ctx.org_id))
    existing_ids = {row[0] for row in existing_result.all()}

    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name or "",
            "image": u.image,
            "already_member": u.id in existing_ids,
        }
        for u in users
    ]


# ---------------------------------------------------------------------------
# Organization Management
# ---------------------------------------------------------------------------


class CreateOrganizationRequest(BaseModel):
    name: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    created_at: Optional[str] = None


class MemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    joined_at: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


def _slugify(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "org"
    # Append short unique suffix to avoid collisions
    slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    return slug


def _project_not_found_error(
    project_id: str,
    *,
    organization_id: str | None = None,
    message: str = "Project not found",
) -> AppError:
    data = {"project_id": project_id}
    if organization_id is not None:
        data["organization_id"] = organization_id
    return NotFoundError(
        code="PROJECT_NOT_FOUND",
        message=message,
        data=data,
        user_action="refresh",
    )


def _organization_member_not_found_error(organization_id: str, user_id: str) -> AppError:
    return NotFoundError(
        code="ORGANIZATION_MEMBER_NOT_FOUND",
        message="Member not found",
        data={"organization_id": organization_id, "user_id": user_id},
        user_action="refresh",
    )


@router.post("/organizations", status_code=201)
async def create_organization(
    req: CreateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> OrganizationResponse:
    """Create a new organization. The current user becomes the owner."""
    if not req.name or not req.name.strip():
        raise InvalidRequestError(
            code="ORGANIZATION_NAME_REQUIRED",
            message="Organization name is required",
            data={"field": "name"},
            user_action="fix_input",
        )

    slug = _slugify(req.name)

    # Create organization
    org = Organization(name=req.name.strip(), slug=slug)
    db.add(org)
    await db.flush()

    # Create owner membership
    member = Member(
        user_id=auth_ctx.user_id,
        organization_id=org.id,
        role="owner",
    )
    db.add(member)

    # Create default project
    project = Project(
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db.add(project)

    await db.commit()
    await db.refresh(org)

    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        created_at=str(org.created_at) if org.created_at else None,
    )


@router.get("/members")
async def list_members(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[MemberResponse]:
    """List members of the current organization."""
    result = await db.execute(
        select(Member, AuthUser)
        .join(AuthUser, Member.user_id == AuthUser.id)
        .where(Member.organization_id == auth_ctx.org_id)
    )
    rows = result.all()
    return [
        MemberResponse(
            user_id=member.user_id,
            email=user.email,
            display_name=user.name,
            role=member.role,
            joined_at=str(member.created_at) if member.created_at else None,
        )
        for member, user in rows
    ]


@router.post("/members/invite", status_code=201)
async def invite_member(
    req: InviteMemberRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> MemberResponse:
    """Invite a user to the current organization by email. Requires admin role."""
    # Look up user by email
    user_result = await db.execute(select(AuthUser).where(AuthUser.email == req.email.strip()).limit(1))
    user = user_result.scalar_one_or_none()
    if not user:
        raise NotFoundError(
            code="AUTH_USER_NOT_FOUND",
            message="User not found with the given email",
            data={"email": req.email.strip()},
            user_action="fix_input",
        )

    # Check if already a member
    existing = await db.execute(
        select(Member)
        .where(
            Member.user_id == user.id,
            Member.organization_id == auth_ctx.org_id,
        )
        .limit(1)
    )
    if existing.scalar_one_or_none():
        raise ResourceConflictError(
            code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
            message="User is already a member of this organization",
            data={"organization_id": auth_ctx.org_id, "user_id": user.id},
            user_action="refresh",
        )

    role = _normalize_assignable_role(req.role)
    _ensure_can_assign_role(auth_ctx.role, role)

    member = Member(
        user_id=user.id,
        organization_id=auth_ctx.org_id,
        role=role.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="member.invited",
        target_type="organization_member",
        target_id=user.id,
        details={"target_email": user.email, "assigned_role": member.role},
    )

    return MemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.name,
        role=member.role,
        joined_at=str(member.created_at) if member.created_at else None,
    )


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> None:
    """Remove a member from the current organization. Cannot remove the owner."""
    # Find the member
    result = await db.execute(
        select(Member)
        .where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        )
        .limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise _organization_member_not_found_error(auth_ctx.org_id, user_id)

    previous_role = member.role
    _ensure_can_modify_member(auth_ctx.role, member.role, JoySafeterRole.VIEWER)

    await db.execute(
        sa_delete(Member).where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        )
    )
    await db.commit()
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="member.removed",
        target_type="organization_member",
        target_id=user_id,
        details={"previous_role": previous_role},
    )


@router.put("/members/{user_id}")
async def update_member_role(
    user_id: str,
    req: UpdateMemberRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_admin),
) -> MemberResponse:
    """Update a member's role. Cannot change the owner's role."""
    # Find the member
    result = await db.execute(
        select(Member)
        .where(
            Member.user_id == user_id,
            Member.organization_id == auth_ctx.org_id,
        )
        .limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise _organization_member_not_found_error(auth_ctx.org_id, user_id)

    new_role = _normalize_assignable_role(req.role)
    _ensure_can_modify_member(auth_ctx.role, member.role, new_role)

    previous_role = member.role
    member.role = new_role.value
    await db.commit()
    await db.refresh(member)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="member.role_updated",
        target_type="organization_member",
        target_id=user_id,
        details={"previous_role": previous_role, "new_role": member.role},
    )

    # Fetch user info
    user_result = await db.execute(select(AuthUser).where(AuthUser.id == user_id).limit(1))
    user = user_result.scalar_one_or_none()

    return MemberResponse(
        user_id=member.user_id,
        email=user.email if user else "",
        display_name=user.name if user else "",
        role=member.role,
        joined_at=str(member.created_at) if member.created_at else None,
    )
