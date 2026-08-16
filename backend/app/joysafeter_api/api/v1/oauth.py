"""Identity federation HTTP routes exposed through the legacy OAuth paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_identity_federation.application.commands import BeginLoginCommand, CompleteLoginCommand
from app.joysafeter_identity_federation.application.results import LoginRestarted, LoginSucceeded
from app.joysafeter_identity_federation.bootstrap import (
    build_federated_account_service,
    build_federated_login_coordinator,
    get_federation_provider_view,
)
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    CallbackContext,
    CorrelationCookie,
    ProviderId,
    RequestContext,
)
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ServiceUnavailableError
from app.joysafeter_shared.common.dependencies import get_current_user, get_db
from app.joysafeter_shared.common.response import success_response
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.rate_limit import get_client_ip

router = APIRouter(tags=["joysafeter-oauth"])

_CORRELATION_COOKIE_NAME = "joysafeter_federation_attempt"

AUTHORIZE_HTTP_STATUS = {
    "FEDERATION_PROVIDER_NOT_ACTIVE": 404,
    "FEDERATION_CALLBACK_URL_INVALID": 400,
    "FEDERATION_STATE_STORE_UNAVAILABLE": 503,
}

CALLBACK_REDIRECT_CODES = {
    "FEDERATION_ATTEMPT_INVALID": "FEDERATION_ATTEMPT_INVALID",
    "FEDERATION_ATTEMPT_MISMATCH": "FEDERATION_ATTEMPT_MISMATCH",
    "FEDERATION_ATTEMPT_EXPIRED": "FEDERATION_ATTEMPT_EXPIRED",
    "FEDERATION_UPSTREAM_DENIED": "FEDERATION_UPSTREAM_DENIED",
    "FEDERATION_UPSTREAM_UNAVAILABLE": "FEDERATION_UPSTREAM_UNAVAILABLE",
    "FEDERATION_ACCOUNT_LINK_REQUIRED": "FEDERATION_ACCOUNT_LINK_REQUIRED",
    "FEDERATION_REGISTRATION_DISABLED": "FEDERATION_REGISTRATION_DISABLED",
    "FEDERATION_SESSION_ISSUE_FAILED": "FEDERATION_SESSION_ISSUE_FAILED",
}

_AUTHORIZE_FALLBACK_CODE = "FEDERATION_UPSTREAM_UNAVAILABLE"


class OAuthProviderInfo(BaseModel):
    id: str
    display_name: str
    icon: str


class OAuthProvidersResponse(BaseModel):
    providers: list[OAuthProviderInfo]
    login_mode: str


class UserOAuthAccount(BaseModel):
    id: str
    provider: str
    provider_account_id: str
    email: str | None
    created_at: datetime


class UserOAuthAccountsResponse(BaseModel):
    accounts: list[UserOAuthAccount]


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_oauth_providers() -> OAuthProvidersResponse:
    view = get_federation_provider_view()
    return OAuthProvidersResponse(
        providers=[
            OAuthProviderInfo(
                id=provider.id,
                display_name=provider.display_name,
                icon=provider.icon,
            )
            for provider in view.providers
        ],
        login_mode=view.login_mode,
    )


@router.get("/{provider}")
async def oauth_authorize(
    provider: str,
    request: Request,
    callback_url: str | None = Query(None, description="Redirect URL after successful login"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        coordinator = build_federated_login_coordinator(db)
        result = await coordinator.begin_login(
            BeginLoginCommand(provider_id=provider, callback_url=callback_url),
            _request_context(request),
        )
    except FederationError as error:
        raise _authorize_error(error) from error
    except Exception as unexpected_error:
        logger.bind(error_type=type(unexpected_error).__name__).error("Identity federation authorization failed")
        raise ServiceUnavailableError(
            "Identity federation authorization failed",
            code=_AUTHORIZE_FALLBACK_CODE,
            retryable=True,
            user_action="retry",
        ) from unexpected_error

    response = JSONResponse(
        content=success_response(
            data={"authorization_url": result.authorization_url, "state": result.state},
            message="OAuth authorization URL generated",
        )
    )
    _set_correlation_cookie(response, result.correlation_cookie)
    return response


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = Query(None, description="Auth code"),
    state: str | None = Query(None, description="State parameter"),
    error: str | None = Query(None, description="Provider error"),
    error_description: str | None = Query(None, description="Provider error description"),
    retry: int = Query(0, description="Legacy callback parameter"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    del code, state, error, error_description, retry
    try:
        coordinator = build_federated_login_coordinator(db)
        result = await coordinator.complete_login(
            CompleteLoginCommand(provider_id=provider),
            _request_context(request, callback=True),
        )

        if isinstance(result, LoginSucceeded):
            response = _create_auth_response(result)
            _clear_correlation_cookie(response, first=True)
            return response

        if isinstance(result, LoginRestarted):
            response = RedirectResponse(url=result.authorization_action.authorization_url, status_code=302)
            _clear_correlation_cookie(response)
            _set_correlation_cookie(response, result.authorization_action.correlation_cookie)
            return response

        raise RuntimeError("Unsupported federation result")
    except FederationError as federation_error:
        error_code = CALLBACK_REDIRECT_CODES.get(
            federation_error.code,
            "FEDERATION_UPSTREAM_UNAVAILABLE",
        )
        response = _redirect_with_error(error_code)
        _clear_correlation_cookie(response)
        return response
    except Exception as unexpected_error:
        logger.bind(error_type=type(unexpected_error).__name__).error("Identity federation callback failed")
        response = _redirect_with_error("FEDERATION_UPSTREAM_UNAVAILABLE")
        _clear_correlation_cookie(response)
        return response


@router.get("/accounts/me", response_model=UserOAuthAccountsResponse)
async def get_my_oauth_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserOAuthAccountsResponse:
    current_user = await get_current_user(None, request, db)
    accounts = await build_federated_account_service(db).list_accounts(current_user.id)
    return UserOAuthAccountsResponse(
        accounts=[
            UserOAuthAccount(
                id=account.id,
                provider=account.provider_id.value,
                provider_account_id=account.subject,
                email=account.email,
                created_at=account.created_at,
            )
            for account in accounts
        ]
    )


@router.delete("/accounts/{provider}")
async def unlink_oauth_account(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current_user = await get_current_user(None, request, db)
    try:
        provider_id = ProviderId(provider)
        success = await build_federated_account_service(db).unlink(current_user.id, provider_id)
    except ValueError as error:
        raise InvalidRequestError("OAuth provider is invalid", code="OAUTH_PROVIDER_NOT_FOUND") from error
    except FederationError as error:
        if error.code == "FEDERATION_LAST_ACCOUNT_UNLINK_FORBIDDEN":
            raise InvalidRequestError(
                "Cannot unlink the only OAuth account. Please set a password first.",
                code="OAUTH_LAST_ACCOUNT_UNLINK_FORBIDDEN",
            ) from error
        if error.code == "FEDERATION_USER_NOT_FOUND":
            raise InvalidRequestError("User not found", code="USER_NOT_FOUND") from error
        raise
    return {"success": success, "provider": provider}


def _request_context(request: Request, *, callback: bool = False) -> RequestContext | CallbackContext:
    base_url = settings.backend_url.rstrip("/")
    raw_path = request.scope.get("raw_path")
    if isinstance(raw_path, bytes):
        path = raw_path.decode("latin-1")
    else:
        path = request.url.path
    query_string = request.scope.get("query_string", b"")
    if isinstance(query_string, bytes):
        query = query_string.decode("latin-1")
    else:
        query = str(query_string)
    request_url = f"{base_url}{path}"
    if query:
        request_url = f"{request_url}?{query}"
    values = {
        "base_url": base_url,
        "request_url": request_url,
        "client_ip": get_client_ip(request),
        "headers": dict(request.headers),
        "cookies": dict(request.cookies),
    }
    if callback:
        return CallbackContext(query=dict(request.query_params), **values)
    return RequestContext(**values)


def _authorize_error(error: FederationError) -> InvalidRequestError | NotFoundError | ServiceUnavailableError:
    public_code = error.code if error.code in AUTHORIZE_HTTP_STATUS else _AUTHORIZE_FALLBACK_CODE
    status_code = AUTHORIZE_HTTP_STATUS.get(public_code, 503)
    kwargs = {
        "message": "Identity federation authorization failed",
        "code": public_code,
        "retryable": error.retryable if public_code == error.code else True,
        "user_action": error.user_action if public_code == error.code else "retry",
    }
    if status_code == 404:
        return NotFoundError(**kwargs)
    if status_code == 503:
        return ServiceUnavailableError(**kwargs)
    return InvalidRequestError(**kwargs)


def _correlation_cookie_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "httponly": True,
        "secure": settings.cookie_secure_effective,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }
    if settings.cookie_domain:
        kwargs["domain"] = settings.cookie_domain
    return kwargs


def _set_correlation_cookie(response: JSONResponse | RedirectResponse, cookie: CorrelationCookie | None) -> None:
    if cookie is None:
        return
    response.set_cookie(
        key=cookie.name,
        value=cookie.value,
        max_age=cookie.max_age_seconds,
        **_correlation_cookie_kwargs(),
    )


def _clear_correlation_cookie(response: RedirectResponse, *, first: bool = False) -> None:
    before = list(response.raw_headers) if first else None
    if first:
        response.raw_headers = [header for header in response.raw_headers if header[0].lower() != b"set-cookie"]
    response.delete_cookie(
        key=_CORRELATION_COOKIE_NAME,
        domain=settings.cookie_domain,
        path="/",
        secure=settings.cookie_secure_effective,
        httponly=True,
        samesite=settings.cookie_samesite,
    )
    if before is not None:
        response.raw_headers.extend(header for header in before if header[0].lower() == b"set-cookie")


def _redirect_with_error(error_code: str) -> RedirectResponse:
    error_url = f"{settings.frontend_url.rstrip('/')}/signin?{urlencode({'error_code': error_code})}"
    return RedirectResponse(url=error_url, status_code=302)


def _create_auth_response(result: LoginSucceeded) -> RedirectResponse:
    if not result.callback_url.startswith("/") or result.callback_url.startswith("//"):
        raise RuntimeError("Federation callback path is invalid")
    response = RedirectResponse(
        url=f"{settings.frontend_url.rstrip('/')}{result.callback_url}",
        status_code=302,
    )
    cookie_kwargs: dict[str, Any] = {
        "httponly": True,
        "samesite": settings.cookie_samesite,
        "secure": settings.cookie_secure_effective,
        "path": "/",
    }
    if settings.cookie_domain:
        cookie_kwargs["domain"] = settings.cookie_domain
    response.set_cookie(
        key=settings.cookie_name,
        value=result.access_token,
        expires=result.access_expires_at,
        **cookie_kwargs,
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        expires=result.refresh_expires_at,
        **cookie_kwargs,
    )
    response.set_cookie(
        key="csrf_token",
        value=result.csrf_token,
        expires=result.access_expires_at,
        **{**cookie_kwargs, "httponly": False},
    )
    return response
