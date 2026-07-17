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

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal, Optional, cast

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_api.services import ApiKeyService, AuthService, AuthSessionService, ProjectService
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_domain.services.joysafeter_organization_service import OrganizationService
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
)
from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    require_joysafeter_user_admin,
    require_joysafeter_user_context,
    require_joysafeter_user_write,
)
from app.joysafeter_shared.common.joysafeter_auth.context import (
    ProjectCapability,
    effective_project_capability,
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
):
    """Return current user + org + project info in the format expected by the frontend."""
    # Look up user
    user_result = await db.execute(select(AuthUser).where(AuthUser.id == auth_ctx.user_id).limit(1))
    user = user_result.scalar_one_or_none()

    # Look up current org
    org_result = await db.execute(select(Organization).where(Organization.id == auth_ctx.org_id).limit(1))
    org = org_result.scalar_one_or_none()

    project_svc = ProjectService(db)
    proj = await project_svc.get_accessible_project(
        project_id=auth_ctx.project_id,
        org_id=auth_ctx.org_id,
        user_id=auth_ctx.user_id,
        org_role=auth_ctx.role,
        allow_archived=True,
    )

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

    # List projects accessible in current org
    all_projects = await project_svc.list_accessible_projects(
        org_id=auth_ctx.org_id,
        user_id=auth_ctx.user_id,
        org_role=auth_ctx.role,
    )
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
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

    project_svc = ProjectService(db)

    # Resolve project
    target_project_id = req.project_id
    if not target_project_id:
        accessible_projects = await project_svc.list_accessible_projects(
            org_id=target_org_id,
            user_id=auth_ctx.user_id,
            org_role=JoySafeterRole.normalize(member.role),
        )
        default_proj = next((project for project in accessible_projects if project.is_default), None)
        if default_proj is None and accessible_projects:
            default_proj = accessible_projects[0]
        if not default_proj:
            raise NotFoundError(
                code="DEFAULT_PROJECT_NOT_FOUND",
                message="No default project found for the organization",
                data={"organization_id": target_org_id},
                user_action="refresh",
            )
        target_project_id = default_proj.id
    else:
        proj = await project_svc.get_accessible_project(
            project_id=target_project_id,
            org_id=target_org_id,
            user_id=auth_ctx.user_id,
            org_role=JoySafeterRole.normalize(member.role),
            allow_archived=True,
        )
        if not proj:
            raise _project_not_found_error(
                target_project_id,
                organization_id=target_org_id,
                message="Project not found in the target organization",
            )

    # Fetch resolved project details and accessible project list
    resolved_project = await project_svc.get_accessible_project(
        project_id=target_project_id,
        org_id=target_org_id,
        user_id=auth_ctx.user_id,
        org_role=JoySafeterRole.normalize(member.role),
        allow_archived=True,
    )
    all_projects = await project_svc.list_accessible_projects(
        org_id=target_org_id,
        user_id=auth_ctx.user_id,
        org_role=JoySafeterRole.normalize(member.role),
    )

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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> list[ProjectResponse]:
    """List projects for the current org."""
    svc = ProjectService(db)
    projects = await svc.list_accessible_projects(
        org_id=auth_ctx.org_id,
        user_id=auth_ctx.user_id,
        org_role=auth_ctx.role,
        include_archived=include_archived,
    )
    return [_project_to_response(p) for p in projects]


@router.post("/projects", status_code=201)
async def create_project(
    req: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> ProjectResponse:
    """Create a new project (requires admin role)."""
    svc = ProjectService(db)
    project = await svc.create_project(
        org_id=auth_ctx.org_id,
        name=req.name,
        slug=req.slug,
        created_by_user_id=auth_ctx.user_id,
    )
    return _project_to_response(project)


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_write),
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_write),
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> ProjectResponse:
    project = await ProjectService(db).get_accessible_project(
        project_id=project_id,
        org_id=auth_ctx.org_id,
        user_id=auth_ctx.user_id,
        org_role=auth_ctx.role,
        allow_archived=True,
    )
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> ProjectResponse:
    try:
        project = await ProjectService(db).update_project(
            project_id,
            auth_ctx.org_id,
            name=req.name,
            slug=req.slug,
        )
    except ValueError:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return _project_to_response(project)


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> dict:
    try:
        await ProjectService(db).archive_project(project_id, auth_ctx.org_id)
    except ValueError:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return {"status": "archived"}


@router.post("/projects/{project_id}/set-default")
async def set_default_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> ProjectResponse:
    try:
        project = await ProjectService(db).restore_project(project_id, auth_ctx.org_id)
    except ValueError:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    return _project_to_response(project)


# ---------------------------------------------------------------------------
# Project member management routes
# ---------------------------------------------------------------------------


class ProjectAccess(str, Enum):
    """A member's effective access to a project."""

    # owner/admin reach every project regardless of ProjectMember rows
    ORG_WIDE = "org_wide"
    # has an explicit ProjectMember row for this project
    EXPLICIT = "explicit"
    # developer/viewer without a row — cannot access
    NONE = "none"


class ProjectMemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    org_role: str
    access: ProjectAccess
    project_role: Optional[str] = None


class AddProjectMemberRequest(BaseModel):
    user_id: str
    # Project role: admin / editor / viewer. Normalized on grant; drives the
    # member's effective capability in this project.
    role: str = "editor"


def _project_member_access(org_role: str, *, has_explicit_row: bool) -> ProjectAccess:
    if ProjectService.role_has_org_wide_project_access(org_role):
        return ProjectAccess.ORG_WIDE
    return ProjectAccess.EXPLICIT if has_explicit_row else ProjectAccess.NONE


async def _require_project_admin_actor(
    svc: ProjectService, auth_ctx: JoySafeterAuthContext, project_id: str
) -> None:
    """Require the caller to be admin OF THIS project (org super-users included).

    Scoped to the path project_id, not the active-context project, so a project
    admin can manage members of exactly the project they administer.
    """
    actor_role = await svc.get_project_member_role(project_id, auth_ctx.user_id)
    if effective_project_capability(auth_ctx.role, actor_role) < ProjectCapability.ADMIN:
        raise AccessDeniedError(
            "Project admin access required",
            code="JOYSAFETER_PROJECT_ADMIN_REQUIRED",
        )


@router.get("/projects/{project_id}/members")
async def list_project_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> list[ProjectMemberResponse]:
    """List organization members with their access status for a project (requires admin role)."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id, auth_ctx.org_id)
    if project is None:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    await _require_project_admin_actor(svc, auth_ctx, project_id)

    explicit_role_by_user = {row.user_id: row.role for row in await svc.list_project_members(project_id)}

    return [
        ProjectMemberResponse(
            user_id=member.user_id,
            email=user.email,
            display_name=user.name,
            org_role=member.role,
            access=_project_member_access(member.role, has_explicit_row=member.user_id in explicit_role_by_user),
            project_role=explicit_role_by_user.get(member.user_id),
        )
        for member, user in await OrganizationMemberService(db).list_members_with_users(auth_ctx.org_id)
    ]


@router.post("/projects/{project_id}/members", status_code=201)
async def add_project_member(
    project_id: str,
    req: AddProjectMemberRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> ProjectMemberResponse:
    """Grant an organization member access to a project (requires admin role)."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id, auth_ctx.org_id)
    if project is None:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    await _require_project_admin_actor(svc, auth_ctx, project_id)

    member = await OrganizationMemberService(db).get_member_by_user_id(auth_ctx.org_id, req.user_id)
    if member is None:
        raise NotFoundError(
            code="ORGANIZATION_MEMBER_NOT_FOUND",
            message="User is not a member of this organization",
            data={"organization_id": auth_ctx.org_id, "user_id": req.user_id},
            user_action="fix_input",
        )
    user = await AuthService(db).get_user_by_id(req.user_id)

    await svc.grant_project_membership(project_id=project_id, user_id=req.user_id, role=req.role, commit=True)

    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="project_member.added",
        target_type="project_member",
        target_id=req.user_id,
        details={"project_id": project_id, "assigned_role": req.role},
    )
    return ProjectMemberResponse(
        user_id=req.user_id,
        email=user.email if user else "",
        display_name=user.name if user else "",
        org_role=member.role,
        access=_project_member_access(member.role, has_explicit_row=True),
        project_role=req.role,
    )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member(
    project_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> None:
    """Revoke an org member's explicit access to a project (requires project admin)."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id, auth_ctx.org_id)
    if project is None:
        raise _project_not_found_error(project_id, organization_id=auth_ctx.org_id)
    await _require_project_admin_actor(svc, auth_ctx, project_id)
    if project.is_default:
        raise InvalidRequestError(
            code="PROJECT_MEMBER_DEFAULT_REMOVE_FORBIDDEN",
            message="Cannot remove a member from the default project. Remove them from the organization instead.",
            data={"project_id": project_id, "user_id": user_id},
            user_action="fix_input",
        )

    revoked = await svc.revoke_project_membership(project_id=project_id, user_id=user_id, commit=True)
    if not revoked:
        raise NotFoundError(
            code="PROJECT_MEMBER_NOT_FOUND",
            message="User has no explicit membership in this project",
            data={"project_id": project_id, "user_id": user_id},
            user_action="refresh",
        )

    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="project_member.removed",
        target_type="project_member",
        target_id=user_id,
        details={"project_id": project_id},
    )


# ---------------------------------------------------------------------------
# User search (for member invite)
# ---------------------------------------------------------------------------


@router.get("/search-users")
async def search_users(
    q: str = Query("", min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
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
    project_id: Optional[str] = None
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


@router.post("/organizations", status_code=201)
async def create_organization(
    req: CreateOrganizationRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> OrganizationResponse:
    """Create a new organization. The current user becomes the owner."""
    created = await OrganizationService(db).create_with_owner_and_default_project(
        name=req.name,
        owner_user_id=auth_ctx.user_id,
    )
    org = created.organization

    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        project_id=created.default_project.id,
        created_at=str(org.created_at) if org.created_at else None,
    )


@router.get("/members")
async def list_members(
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_context),
) -> list[MemberResponse]:
    """List members of the current organization."""
    rows = await OrganizationMemberService(db).list_members_with_users(auth_ctx.org_id)
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> MemberResponse:
    """Invite a user to the current organization by email. Requires admin role."""
    member, user = await OrganizationMemberService(db).invite_member_by_email(
        organization_id=auth_ctx.org_id,
        actor_role=auth_ctx.role,
        email=req.email,
        role=req.role,
    )
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> None:
    """Remove a member from the current organization. Cannot remove the owner."""
    member = await OrganizationMemberService(db).remove_member_by_user_id(
        organization_id=auth_ctx.org_id,
        user_id=user_id,
        actor_role=auth_ctx.role,
    )
    previous_role = member.role
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_user_admin),
) -> MemberResponse:
    """Update a member's role. Cannot change the owner's role."""
    existing_member = await OrganizationMemberService(db).get_member_by_user_id(auth_ctx.org_id, user_id)
    previous_role = existing_member.role if existing_member is not None else None
    member = await OrganizationMemberService(db).update_member_role_by_user_id(
        organization_id=auth_ctx.org_id,
        user_id=user_id,
        actor_role=auth_ctx.role,
        role=req.role,
    )
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
