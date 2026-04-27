"""
OAuth/OIDC auth API endpoints.

Provides OAuth login flow APIs:
- GET /oauth/providers - list enabled providers
- GET /oauth/{provider} - start OAuth authorization
- GET /oauth/{provider}/callback - handle OAuth callback

Multi-protocol support:
- oauth2 (standard): GitHub, Google, Microsoft, GitLab, etc.
- jd_sso (JD SSA): JD enterprise login
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_db
from app.common.response import success_response
from app.core.oauth import get_oauth_config, get_protocol_handler
from app.core.redis import RedisClient
from app.core.security import create_access_token, create_csrf_token, generate_refresh_token
from app.core.settings import settings
from app.services.oauth_service import OAuthService

LOG_PREFIX = "[OAuthAPI]"
router = APIRouter(prefix="/v1/auth/oauth", tags=["OAuth"])


# ==================== Response Models ====================


class OAuthProviderInfo(BaseModel):
    """OAuth provider info (no sensitive fields)."""

    id: str
    display_name: str
    icon: str


class OAuthProvidersResponse(BaseModel):
    """OAuth provider list response."""

    providers: List[OAuthProviderInfo]


# ==================== API Endpoints ====================


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_oauth_providers() -> OAuthProvidersResponse:
    """
    List enabled OAuth providers.

    Used by frontend to render SSO buttons.
    """
    oauth_config = get_oauth_config()
    providers = oauth_config.list_providers()

    return OAuthProvidersResponse(providers=[OAuthProviderInfo(**p) for p in providers])


@router.get("/{provider}")
async def oauth_authorize(
    provider: str,
    request: Request,
    callback_url: Optional[str] = Query(None, description="Redirect URL after successful login"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Start OAuth authorization flow.

    Redirect users to the provider's authorization page.

    Args:
        provider: Provider key (e.g. "github", "google", "jd")
        callback_url: Redirect URL after login (optional)
    """
    oauth_config = get_oauth_config()
    oauth_service = OAuthService(db)

    # Build callback URL
    base_url = _get_base_url(request)
    redirect_uri = f"{base_url}/api/v1/auth/oauth/{provider}/callback"

    # Generate state (includes callback_url)
    state = secrets.token_urlsafe(32)
    state_data = {
        "provider": provider,
        "redirect_uri": redirect_uri,
        "callback_url": callback_url or oauth_config.settings.default_redirect_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store state in Redis
    if RedisClient.is_available():
        try:
            await RedisClient.set(f"oauth_state:{state}", json.dumps(state_data), expire=600)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Failed to store state in Redis: {e}")

    authorization_url, resolved_state = await oauth_service.generate_authorization_url(
        provider_name=provider,
        redirect_uri=redirect_uri,
        state=state,
    )

    logger.info(f"{LOG_PREFIX} Generated authorization URL for {provider}")
    return success_response(
        data={
            "authorization_url": authorization_url,
            "state": resolved_state,
        },
        message="OAuth authorization URL generated",
    )


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(None, description="Auth code (required for OAuth2, optional for JD SSO)"),
    state: Optional[str] = Query(None, description="State parameter (optional for JD SSO)"),
    error: Optional[str] = Query(None, description="Error message"),
    error_description: Optional[str] = Query(None, description="Error description"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Handle OAuth callback.

    Validate authorization, fetch user info, create/link user, issue JWT tokens.

    Multi-protocol support (by provider protocol field):
    - oauth2 (standard): exchange code for token, then userinfo
    - jd_sso (JD SSA): use Cookie + verifyTicket for userinfo
    """
    oauth_config = get_oauth_config()
    frontend_url = settings.frontend_url.rstrip("/")

    # Handle user denial
    if error:
        logger.warning(f"{LOG_PREFIX} OAuth error: {error} - {error_description}")
        return _redirect_with_error(frontend_url, "OAUTH_ACCESS_DENIED", error_description or error)

    # 2. Load provider config (needed to detect protocol)
    provider_config = oauth_config.get_provider(provider)
    if not provider_config:
        logger.error(f"{LOG_PREFIX} Provider not found: {provider}")
        return _redirect_with_error(frontend_url, "OAUTH_PROVIDER_NOT_FOUND")

    # 1. Validate state (JD SSO can skip; it relies on Cookie, not auth code)
    callback_url = oauth_config.settings.default_redirect_url
    state_data: dict[Any, Any] | None = {}

    if state:
        # Validate when state is present
        state_data, callback_url = await _validate_state(state, oauth_config)
        if state_data is None:
            return _redirect_with_error(frontend_url, "OAUTH_STATE_INVALID")

        # Validate provider match
        if state_data.get("provider") != provider:
            logger.warning(f"{LOG_PREFIX} Provider mismatch: expected {state_data.get('provider')}, got {provider}")
            return _redirect_with_error(frontend_url, "OAUTH_PROVIDER_MISMATCH")
    elif provider_config.protocol != "jd_sso":
        # Non-JD SSO protocols require state
        logger.warning(f"{LOG_PREFIX} Missing state parameter for {provider_config.protocol}")
        return _redirect_with_error(frontend_url, "OAUTH_STATE_MISSING")

    try:
        # 3. Use protocol handler to fetch user info
        handler = get_protocol_handler(provider_config.protocol)
        redirect_uri = (state_data or {}).get(
            "redirect_uri"
        ) or f"{_get_base_url(request)}/api/v1/auth/oauth/{provider}/callback"

        logger.info(f"{LOG_PREFIX} Processing {provider_config.protocol} callback for {provider}")

        user_info = await handler.get_user_info(
            request=request,
            provider_config=provider_config,
            code=code,
            redirect_uri=redirect_uri,
        )

        # 4. Find or create user
        oauth_service = OAuthService(db)
        user, is_new_user = await oauth_service.find_or_create_user(
            provider_name=provider,
            provider_account_id=user_info.provider_id,
            email=user_info.email,
            name=user_info.name,
            avatar=user_info.avatar,
            tokens={},  # Tokens handled by protocol handler
            raw_userinfo=user_info.raw,
        )

        # 5. Commit transaction & post-login init
        await db.commit()
        ip_address = _get_client_ip(request)

        from app.services.login_init import run_post_login_init

        await run_post_login_init(db, user, ip_address)

        # 6. Issue JWT tokens
        jwt_access_token = create_access_token(
            subject=user.id,
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )
        jwt_refresh_token = generate_refresh_token()
        csrf_token = create_csrf_token(user.id)

        # Store refresh token in Redis
        await _store_refresh_token(jwt_refresh_token, user.id)

        # 7. Set cookies and redirect
        response = _create_auth_response(
            frontend_url=frontend_url,
            callback_url=callback_url,
            access_token=jwt_access_token,
            refresh_token=jwt_refresh_token,
            csrf_token=csrf_token,
        )

        logger.info(
            f"{LOG_PREFIX} OAuth login successful",
            extra={"provider": provider, "user_id": user.id, "is_new_user": is_new_user},
        )

        return response

    except InvalidRequestError:
        raise
    except ValueError as e:
        # Validation error raised by protocol handler
        logger.error(f"{LOG_PREFIX} OAuth callback validation error: {e}")
        await db.rollback()
        return _redirect_with_error(frontend_url, "OAUTH_CALLBACK_INVALID", str(e))
    except Exception as e:
        logger.error(f"{LOG_PREFIX} OAuth callback error: {e}", exc_info=True)
        await db.rollback()
        return _redirect_with_error(frontend_url, "OAUTH_CALLBACK_FAILED", str(e))


# ==================== User OAuth Account Management ====================


class UserOAuthAccount(BaseModel):
    """User OAuth account info."""

    id: str
    provider: str
    provider_account_id: str
    email: Optional[str]
    created_at: datetime


class UserOAuthAccountsResponse(BaseModel):
    """User OAuth account list response."""

    accounts: List[UserOAuthAccount]


@router.get("/accounts/me", response_model=UserOAuthAccountsResponse)
async def get_my_oauth_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserOAuthAccountsResponse:
    """Get OAuth account bindings for current user."""
    from app.common.dependencies import get_current_user

    current_user = await get_current_user(None, request, db)
    oauth_service = OAuthService(db)
    accounts = await oauth_service.get_user_oauth_accounts(current_user.id)

    return UserOAuthAccountsResponse(
        accounts=[
            UserOAuthAccount(
                id=acc.id,
                provider=acc.provider,
                provider_account_id=acc.provider_account_id,
                email=acc.email,
                created_at=acc.created_at,
            )
            for acc in accounts
        ]
    )


@router.delete("/accounts/{provider}")
async def unlink_oauth_account(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Unlink OAuth account."""
    from app.common.dependencies import get_current_user

    current_user = await get_current_user(None, request, db)
    oauth_service = OAuthService(db)
    success = await oauth_service.unlink_oauth_account(current_user.id, provider)

    if success:
        await db.commit()

    return {"success": success, "provider": provider}


# ==================== Helpers ====================


def _get_base_url(request: Request) -> str:
    """Get base URL, with proxy support."""
    base_url = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        proto = forwarded_proto or "https"
        base_url = f"{proto}://{forwarded_host}"
    return base_url


def _get_client_ip(request: Request) -> str:
    """Get client IP, with proxy support."""
    ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    return ip


def _redirect_with_error(frontend_url: str, error_code: str, message: Optional[str] = None) -> RedirectResponse:
    """Build error redirect response."""
    params = {"error_code": error_code}
    if message:
        params["error_message"] = message
    error_url = f"{frontend_url}/signin?{urlencode(params)}"
    return RedirectResponse(url=error_url, status_code=302)


async def _validate_state(state: str, oauth_config) -> tuple[Optional[Dict], str]:
    """Validate state and return state_data and callback_url."""
    callback_url = oauth_config.settings.default_redirect_url

    if not RedisClient.is_available():
        return {}, callback_url

    try:
        state_key = f"oauth_state:{state}"
        state_data_str = await RedisClient.get(state_key)
        if state_data_str:
            state_data = json.loads(state_data_str)
            callback_url = state_data.get("callback_url", callback_url)
            await RedisClient.delete(state_key)
            return state_data, callback_url
        else:
            logger.warning(f"{LOG_PREFIX} Invalid or expired state: {state[:20]}...")
            return None, callback_url
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Failed to validate state: {e}")
        return {}, callback_url


async def _store_refresh_token(refresh_token: str, user_id: str) -> None:
    """Store refresh token in Redis."""
    if not RedisClient.is_available():
        return

    try:
        expire_seconds = settings.refresh_token_expire_days * 24 * 60 * 60
        await RedisClient.set(f"refresh_token:{refresh_token}", user_id, expire=expire_seconds)
        await RedisClient.set(f"account_refresh_token:{user_id}", refresh_token, expire=expire_seconds)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Failed to store refresh token: {e}")


def _create_auth_response(
    frontend_url: str,
    callback_url: str,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> RedirectResponse:
    """Create redirect response with auth cookies."""
    if not callback_url.startswith("/"):
        callback_url = f"/{callback_url}"
    final_url = f"{frontend_url}{callback_url}"

    response = RedirectResponse(url=final_url, status_code=302)

    # Cookie defaults
    cookie_kwargs: Dict[str, Any] = {
        "httponly": True,
        "samesite": settings.cookie_samesite,
        "secure": settings.cookie_secure_effective,
        "path": "/",
    }
    if settings.cookie_domain:
        cookie_kwargs["domain"] = settings.cookie_domain

    # Access token
    access_expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    response.set_cookie(key=settings.cookie_name, value=access_token, expires=access_expires, **cookie_kwargs)

    # Refresh token
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    response.set_cookie(key="refresh_token", value=refresh_token, expires=refresh_expires, **cookie_kwargs)

    # CSRF token (not httponly)
    csrf_kwargs = {**cookie_kwargs, "httponly": False}
    response.set_cookie(key="csrf_token", value=csrf_token, expires=access_expires, **csrf_kwargs)

    return response
