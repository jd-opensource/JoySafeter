"""Auth controller endpoints (reworked for auth.user & auth.session)."""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional, cast

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import UnauthorizedException
from app.common.response import success_response
from app.core.database import get_db
from app.core.rate_limit import auth_rate_limit, strict_rate_limit
from app.core.security import Token, decode_token
from app.core.settings import settings
from app.models.auth import AuthUser
from app.services.auth_service import AuthService
from app.services.auth_session_service import AuthSessionService

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

# Type alias for SameSite cookie attribute
SameSiteType = Literal["lax", "strict", "none"]


def _get_samesite_value(value: str) -> Optional[SameSiteType]:
    """Convert string to SameSite literal type for cookie operations."""
    normalized = value.lower().strip()
    if normalized in ("lax", "strict", "none"):
        return cast(SameSiteType, normalized)
    return None


# Schemas


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=100)
    image: Optional[str] = None
    is_super_user: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=100)


class SearchUsersResponse(BaseModel):
    id: str
    email: str
    name: str
    image: Optional[str]
    email_verified: bool
    is_super_user: bool


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    image: Optional[str]
    email_verified: bool
    is_super_user: bool


# Endpoints


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
        is_super_user=body.is_super_user,
    )

    # 注册成功后不自动登录，不设置 Cookie
    # 用户需要手动登录
    # 只返回用户信息，不返回 token
    user_data = data.get("user", {})

    return success_response(data={"user": user_data}, message="Registration successful. Please sign in to continue.")


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

    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token")
    csrf_token = result.get("csrf_token")
    expires_in = result.get("expires_in", 259200)

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

    # CSRF token 通过响应体返回，而不是非 HttpOnly Cookie
    # 前端需要将其存储在内存中并通过 X-CSRF-Token header 发送
    # 这样避免了 XSS 攻击窃取 CSRF token 的风险
    if csrf_token:
        result["csrf_token"] = csrf_token

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
        except (UnauthorizedException, HTTPException):
            pass

        if refresh_token and user_id:
            try:
                await service._delete_refresh_token(refresh_token, user_id)
            except Exception:
                pass

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
        response.delete_cookie(
            key=settings.cookie_name,
            domain=settings.cookie_domain,
            path="/",
        )
        response.delete_cookie(
            key="refresh_token",
            domain=settings.cookie_domain,
            path="/",
        )
        response.delete_cookie(
            key="csrf_token",
            domain=settings.cookie_domain,
            path="/",
        )

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


class ResetPasswordForCurrentUserRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


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
        # 传递 request 对象以便从 Cookie 读取 token
        current_user = await _get_current_auth_user(token, db, request)
        return success_response(data={"user": _user_to_response(current_user)})
    except (UnauthorizedException, HTTPException):
        # 未登录时返回 null user
        return success_response(data={"user": None})


@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Header(None, alias="Authorization"),
):
    """Refresh access token using refresh token from Cookie or Authorization header."""

    service = AuthService(db)

    # 尝试从 Cookie 中获取 refresh token
    refresh_token_value = None
    try:
        refresh_token_value = request.cookies.get("refresh_token")
    except Exception:
        pass

    if not refresh_token_value and token:
        try:
            bearer_token = token.replace("Bearer ", "") if token.startswith("Bearer ") else token
            payload = decode_token(bearer_token)
            if payload:
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
                    return success_response(
                        data={
                            "access_token": access_token,
                            "token_type": "bearer",
                            "expires_in": int((access_expires - datetime.now(timezone.utc)).total_seconds()),
                        }
                    )
        except Exception:
            pass

    if refresh_token_value:
        try:
            result = await service.refresh_token(refresh_token_value)
            return success_response(
                data={
                    "access_token": result["access_token"],
                    "token_type": result["token_type"],
                    "expires_in": result["expires_in"],
                }
            )
        except Exception:
            pass

    raise UnauthorizedException("Invalid or expired refresh token")


# Helpers


def _extract_bearer(auth_header: Optional[str]) -> str:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return auth_header.split(" ", 1)[1]


async def _get_current_auth_user(
    auth_header: Optional[str], db: AsyncSession, request: Optional[Request] = None
) -> AuthUser:
    """从 Bearer token 或 Cookie 校验并返回 AuthUser（支持 JWT token 和 session token）。"""
    token = None

    if auth_header:
        try:
            token = _extract_bearer(auth_header)
        except HTTPException:
            pass

    if not token and request:
        try:
            token = (
                request.cookies.get(settings.cookie_name)
                or request.cookies.get("session-token")
                or request.cookies.get("session_token")
                or request.cookies.get("access_token")
                or request.cookies.get("auth_token")
            )
        except Exception:
            pass

    if not token:
        raise UnauthorizedException("Missing credentials")

    user_service = AuthService(db)

    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        user = await user_service.get_user_by_id(str(user_id))
        if user and user.is_active:
            return user
        raise UnauthorizedException("User not found or inactive")

    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        user = await user_service.user_repo.get(uuid.UUID(session.user_id))
        if user and user.is_active:
            return user
        raise UnauthorizedException("User not found or inactive")

    raise UnauthorizedException("Invalid or expired token")


def _user_to_response(user: AuthUser) -> UserResponse:
    """Serialize AuthUser into response-friendly dict."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        image=user.image,
        email_verified=user.email_verified,
        is_super_user=user.is_super_user,
    )
