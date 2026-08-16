from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.joysafeter_api.api.v1 import oauth as oauth_api
from app.joysafeter_identity_federation.application.commands import BeginLoginCommand, CompleteLoginCommand
from app.joysafeter_identity_federation.application.results import BeginLoginResult, LoginRestarted, LoginSucceeded
from app.joysafeter_identity_federation.bootstrap import FederationProviderInfo, FederationProviderView
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    AuthorizationAction,
    CallbackContext,
    CorrelationCookie,
    FederatedAccountView,
    ProviderId,
    RequestContext,
)
from app.joysafeter_shared.common import dependencies
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.config.settings import Settings, settings

pytestmark = pytest.mark.no_db

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _Coordinator:
    def __init__(
        self,
        *,
        begin_result: BeginLoginResult | None = None,
        complete_result: LoginSucceeded | LoginRestarted | None = None,
        begin_error: Exception | None = None,
        complete_error: Exception | None = None,
    ) -> None:
        self.begin_result = begin_result
        self.complete_result = complete_result
        self.begin_error = begin_error
        self.complete_error = complete_error
        self.begin_calls: list[tuple[BeginLoginCommand, RequestContext]] = []
        self.complete_calls: list[tuple[CompleteLoginCommand, CallbackContext]] = []

    async def begin_login(self, command: BeginLoginCommand, context: RequestContext) -> BeginLoginResult:
        self.begin_calls.append((command, context))
        if self.begin_error is not None:
            raise self.begin_error
        assert self.begin_result is not None
        return self.begin_result

    async def complete_login(
        self,
        command: CompleteLoginCommand,
        context: CallbackContext,
    ) -> LoginSucceeded | LoginRestarted:
        self.complete_calls.append((command, context))
        if self.complete_error is not None:
            raise self.complete_error
        assert self.complete_result is not None
        return self.complete_result


@dataclass
class _AccountService:
    accounts: tuple[FederatedAccountView, ...] = ()
    unlink_result: bool = False

    def __post_init__(self) -> None:
        self.listed_user_ids: list[str] = []
        self.unlink_calls: list[tuple[str, ProviderId]] = []

    async def list_accounts(self, user_id: str) -> tuple[FederatedAccountView, ...]:
        self.listed_user_ids.append(user_id)
        return self.accounts

    async def unlink(self, user_id: str, provider_id: ProviderId) -> bool:
        self.unlink_calls.append((user_id, provider_id))
        return self.unlink_result


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(oauth_api.router, prefix="/api/v1/auth/oauth")
    app.dependency_overrides[oauth_api.get_db] = lambda: object()

    async def current_user(*_args, **_kwargs):
        return SimpleNamespace(id="user-1")

    monkeypatch.setattr(dependencies, "get_current_user", current_user)
    monkeypatch.setattr(oauth_api, "get_current_user", current_user, raising=False)
    monkeypatch.setattr(settings, "backend_url", "https://api.public.example")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example")
    monkeypatch.setattr(settings, "cookie_name", "auth_token")
    monkeypatch.setattr(settings, "cookie_domain", None)
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cookie_samesite", "lax")
    monkeypatch.setattr(settings, "trust_forwarded_headers", False)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


def _patch_coordinator(monkeypatch: pytest.MonkeyPatch, coordinator: _Coordinator) -> None:
    monkeypatch.setattr(oauth_api, "build_federated_login_coordinator", lambda _db: coordinator, raising=False)


def test_provider_response_contains_login_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    view = FederationProviderView(
        providers=(FederationProviderInfo(id="jd", display_name="JD SSO", icon="building"),),
        login_mode="redirect",
    )
    monkeypatch.setattr(oauth_api, "get_federation_provider_view", lambda: view, raising=False)

    response = client.get("/api/v1/auth/oauth/providers")

    assert response.status_code == 200
    assert response.json() == {
        "providers": [{"id": "jd", "display_name": "JD SSO", "icon": "building"}],
        "login_mode": "redirect",
    }


def test_authorize_delegates_with_canonical_context_and_sets_correlation_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _Coordinator(
        begin_result=BeginLoginResult(
            authorization_url="https://github.com/login/oauth/authorize?state=attempt-1",
            state="attempt-1",
            correlation_cookie=CorrelationCookie(
                name="joysafeter_federation_attempt",
                value="signed-attempt",
                max_age_seconds=600,
            ),
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    response = client.get(
        "/api/v1/auth/oauth/github?callback_url=/managed/dashboard",
        headers={
            "host": "attacker.example",
            "x-forwarded-host": "forwarded-attacker.example",
            "x-forwarded-for": "203.0.113.9",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "OAuth authorization URL generated"
    assert payload["data"] == {
        "authorization_url": "https://github.com/login/oauth/authorize?state=attempt-1",
        "state": "attempt-1",
    }
    assert coordinator.begin_calls[0][0] == BeginLoginCommand(
        provider_id="github",
        callback_url="/managed/dashboard",
    )
    context = coordinator.begin_calls[0][1]
    assert context.base_url == "https://api.public.example"
    assert context.request_url == (
        "https://api.public.example/api/v1/auth/oauth/github?callback_url=/managed/dashboard"
    )
    assert context.client_ip != "203.0.113.9"
    assert context.headers["host"] == "attacker.example"
    assert context.cookies == {}
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith("joysafeter_federation_attempt=signed-attempt;")
    assert "HttpOnly" in set_cookie
    assert "Max-Age=600" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("FEDERATION_PROVIDER_NOT_ACTIVE", 404),
        ("FEDERATION_CALLBACK_URL_INVALID", 400),
        ("FEDERATION_STATE_STORE_UNAVAILABLE", 503),
    ],
)
def test_authorize_maps_stable_federation_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status_code: int,
) -> None:
    coordinator = _Coordinator(begin_error=FederationError(code=code, message="internal federation detail"))
    _patch_coordinator(monkeypatch, coordinator)

    response = client.get("/api/v1/auth/oauth/github")

    assert response.status_code == status_code
    assert response.json()["code"] == code


def test_authorize_unknown_federation_error_maps_to_stable_unavailable_code(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _Coordinator(
        begin_error=FederationError(
            code="FEDERATION_INTERNAL_SECRET_DETAIL",
            message="secret upstream body",
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    response = client.get("/api/v1/auth/oauth/github")

    assert response.status_code == 503
    assert response.json()["code"] == "FEDERATION_UPSTREAM_UNAVAILABLE"
    assert "SECRET_DETAIL" not in response.text
    assert "secret upstream body" not in response.text


def test_callback_success_uses_result_redirect_and_auth_cookie_order(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _Coordinator(
        complete_result=LoginSucceeded(
            callback_url="/managed/dashboard?tab=identity",
            access_token="access-token",
            refresh_token="refresh-token",
            csrf_token="csrf-token",
            access_expires_at=_NOW + timedelta(minutes=15),
            refresh_expires_at=_NOW + timedelta(days=30),
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    client.cookies.set("joysafeter_federation_attempt", "old-cookie")
    response = client.get(
        "/api/v1/auth/oauth/github/callback?code=upstream-code&state=attempt-1&callback_url=https://evil.example",
        headers={"host": "evil.example", "x-forwarded-host": "evil-forwarded.example"},
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.example/managed/dashboard?tab=identity"
    command, context = coordinator.complete_calls[0]
    assert command == CompleteLoginCommand(provider_id="github")
    assert context.base_url == "https://api.public.example"
    assert context.request_url == (
        "https://api.public.example/api/v1/auth/oauth/github/callback"
        "?code=upstream-code&state=attempt-1&callback_url=https://evil.example"
    )
    assert context.query == {
        "code": "upstream-code",
        "state": "attempt-1",
        "callback_url": "https://evil.example",
    }
    cookies = response.headers.get_list("set-cookie")
    assert cookies[0].startswith("joysafeter_federation_attempt=")
    assert "Max-Age=0" in cookies[0]
    assert cookies[1].startswith("auth_token=access-token;")
    assert "HttpOnly" in cookies[1]
    assert cookies[2].startswith("refresh_token=refresh-token;")
    assert "HttpOnly" in cookies[2]
    assert cookies[3].startswith("csrf_token=csrf-token;")
    assert "HttpOnly" not in cookies[3]


@pytest.mark.parametrize(
    "callback_url",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "managed/dashboard",
        "/managed\\evil",
        "/%2f%2fevil.example/path",
        "/%5cevil.example/path",
        "/%25evil.example/path",
        "/../admin",
        "/%2e%2e/admin",
        "/managed\nnext",
        "/managed path",
        "/%GG",
        123,
    ],
)
def test_callback_malformed_application_path_fails_closed_without_auth_cookies(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    callback_url: object,
) -> None:
    coordinator = _Coordinator(
        complete_result=LoginSucceeded(
            callback_url=callback_url,
            access_token="access-token",
            refresh_token="refresh-token",
            csrf_token="csrf-token",
            access_expires_at=_NOW + timedelta(minutes=15),
            refresh_expires_at=_NOW + timedelta(days=7),
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    response = client.get("/api/v1/auth/oauth/github/callback?code=upstream-code&state=attempt-1")

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://app.example/signin?error_code=FEDERATION_CALLBACK_FAILED"
    )
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1
    assert cookies[0].startswith("joysafeter_federation_attempt=")
    assert "Max-Age=0" in cookies[0]
    assert "access-token" not in response.headers["set-cookie"]
    assert "refresh-token" not in response.headers["set-cookie"]
    assert "csrf-token" not in response.headers["set-cookie"]


def test_callback_restart_clears_old_cookie_before_replacement(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _Coordinator(
        complete_result=LoginRestarted(
            authorization_action=AuthorizationAction(
                authorization_url="https://sso.jd.com/authorize?state=attempt-2",
                correlation_cookie=CorrelationCookie(
                    name="joysafeter_federation_attempt",
                    value="replacement-cookie",
                    max_age_seconds=600,
                ),
            ),
            clear_correlation_cookie=True,
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    client.cookies.set("joysafeter_federation_attempt", "old-cookie")
    response = client.get("/api/v1/auth/oauth/jd/callback")

    assert response.status_code == 302
    assert response.headers["location"] == "https://sso.jd.com/authorize?state=attempt-2"
    cookies = response.headers.get_list("set-cookie")
    assert cookies[0].startswith("joysafeter_federation_attempt=")
    assert "Max-Age=0" in cookies[0]
    assert cookies[1].startswith("joysafeter_federation_attempt=replacement-cookie;")
    assert "Max-Age=600" in cookies[1]


@pytest.mark.parametrize(
    "error_code",
    ["FEDERATION_UPSTREAM_DENIED", "FEDERATION_ATTEMPT_INVALID"],
)
def test_callback_federation_error_redirects_with_only_stable_code_and_clears_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    coordinator = _Coordinator(
        complete_error=FederationError(
            code=error_code,
            message="secret upstream body ticket=credential",
            data={"claims": {"token": "secret"}},
        )
    )
    _patch_coordinator(monkeypatch, coordinator)

    client.cookies.set("joysafeter_federation_attempt", "old-cookie")
    response = client.get("/api/v1/auth/oauth/jd/callback?code=secret-code&ticket=secret-ticket")

    assert response.status_code == 302
    assert response.headers["location"] == f"https://app.example/signin?error_code={error_code}"
    assert "secret" not in response.headers["location"]
    assert "ticket" not in response.headers["location"]
    assert "claims" not in response.headers["location"]
    assert "Max-Age=0" in response.headers.get_list("set-cookie")[0]


def test_callback_unexpected_error_uses_stable_generic_code_without_leak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _Coordinator(complete_error=RuntimeError("upstream body contains secret"))
    _patch_coordinator(monkeypatch, coordinator)

    response = client.get("/api/v1/auth/oauth/github/callback?code=secret-code")

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://app.example/signin?error_code=FEDERATION_UPSTREAM_UNAVAILABLE"
    )
    assert "secret" not in response.headers["location"]
    assert "Max-Age=0" in response.headers.get_list("set-cookie")[0]


def test_callback_factory_failure_uses_stable_redirect_and_clears_cookie(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_build(_db):
        raise RuntimeError("redis endpoint secret-host.internal")

    monkeypatch.setattr(oauth_api, "build_federated_login_coordinator", fail_to_build, raising=False)
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    client.cookies.set("joysafeter_federation_attempt", "old-cookie")

    response = client.get("/api/v1/auth/oauth/github/callback?code=secret-code")

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://app.example/signin?error_code=FEDERATION_UPSTREAM_UNAVAILABLE"
    )
    assert "secret" not in response.headers["location"]
    assert "Max-Age=0" in response.headers.get_list("set-cookie")[0]


def test_request_context_uses_trusted_proxy_client_ip_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backend_url", "https://api.public.example")
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("attacker.example", 80),
            "client": ("10.0.0.9", 12345),
            "path": "/api/v1/auth/oauth/jd/callback",
            "raw_path": b"/api/v1/auth/oauth/jd/callback",
            "query_string": b"ticket=a%2Fb",
            "headers": [
                (b"host", b"attacker.example"),
                (b"x-forwarded-host", b"forwarded-attacker.example"),
                (b"x-forwarded-for", b"203.0.113.7, 198.51.100.2"),
            ],
        }
    )

    context = oauth_api._request_context(request, callback=True)

    assert isinstance(context, CallbackContext)
    assert context.base_url == "https://api.public.example"
    assert context.request_url == "https://api.public.example/api/v1/auth/oauth/jd/callback?ticket=a%2Fb"
    assert context.client_ip == "203.0.113.7"


def test_request_context_ignores_forwarded_ip_from_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backend_url", "https://api.public.example")
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("attacker.example", 80),
            "client": ("198.51.100.9", 12345),
            "path": "/api/v1/auth/oauth/github",
            "raw_path": b"/api/v1/auth/oauth/github",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", b"203.0.113.7")],
        }
    )

    context = oauth_api._request_context(request)

    assert context.base_url == "https://api.public.example"
    assert context.request_url == "https://api.public.example/api/v1/auth/oauth/github"
    assert context.client_ip == "198.51.100.9"


@pytest.mark.parametrize(
    "backend_url",
    [
        "ftp://api.example.com",
        "https://user:pass@api.example.com",
        "https://api.example.com/base-path",
        "https://api.example.com?",
        "https://api.example.com#",
        " https://api.example.com",
        "https://api.example.com ",
        "https://api.example.com bad",
        "https://api.example.com%2fevil.example",
        "https://api.example.com\n.evil.example",
        "https://api.example.com:",
        "https://api.example.com:0",
        "https://[v1.fe]",
        "https://[example.com]",
        "https://127.1",
        "https://010.0.0.1",
        "https://2130706433",
        "https://0x7f000001",
        "https://0x7f.1",
        "https://127.0.0",
        "https://127.0.0.1.2",
        "https://api_example.com",
        "https://-api.example.com",
        "https://api-.example.com",
        "https://.example.com",
        "https://example..com",
        "https://example.com.",
        f"https://{'a' * 64}.example.com",
        f"https://{'.'.join(['a' * 63] * 4)}",
    ],
)
def test_backend_url_rejects_malformed_authority_text(
    monkeypatch: pytest.MonkeyPatch,
    backend_url: str,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BACKEND_URL", backend_url)

    with pytest.raises(ValueError, match="BACKEND_URL"):
        Settings(_env_file=None)


def test_backend_url_defaults_to_local_api_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("BACKEND_URL", raising=False)

    configured = Settings(_env_file=None)

    assert configured.backend_url == "http://localhost:8000"


def test_backend_url_normalizes_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com:8443/")

    configured = Settings(_env_file=None)

    assert configured.backend_url == "https://api.example.com:8443"


@pytest.mark.parametrize(
    ("backend_url", "expected"),
    [
        ("http://192.0.2.10:8080/", "http://192.0.2.10:8080"),
        ("https://[2001:db8::1]:8443", "https://[2001:db8::1]:8443"),
        ("https://bücher.example", "https://xn--bcher-kva.example"),
    ],
)
def test_backend_url_accepts_ip_literals_and_normalizes_idna_hosts(
    monkeypatch: pytest.MonkeyPatch,
    backend_url: str,
    expected: str,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BACKEND_URL", backend_url)

    configured = Settings(_env_file=None)

    assert configured.backend_url == expected


def test_production_requires_explicit_backend_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("BACKEND_URL", raising=False)

    with pytest.raises(ValueError, match="BACKEND_URL.*production"):
        Settings(_env_file=None)


def test_production_accepts_explicit_public_backend_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")

    configured = Settings(_env_file=None)

    assert configured.backend_url == "https://api.example.com"


def test_account_list_and_unlink_use_federated_account_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AccountService(
        accounts=(
            FederatedAccountView(
                id="account-1",
                provider_id=ProviderId("github"),
                subject="github-user-1",
                email="User@Example.com",
                created_at=_NOW,
            ),
        ),
        unlink_result=True,
    )
    monkeypatch.setattr(oauth_api, "build_federated_account_service", lambda _db: service, raising=False)

    listed = client.get("/api/v1/auth/oauth/accounts/me")
    unlinked = client.delete("/api/v1/auth/oauth/accounts/github")

    assert listed.status_code == 200
    assert listed.json() == {
        "accounts": [
            {
                "id": "account-1",
                "provider": "github",
                "provider_account_id": "github-user-1",
                "email": "user@example.com",
                "created_at": "2026-08-15T12:00:00Z",
            }
        ]
    }
    assert unlinked.status_code == 200
    assert unlinked.json() == {"success": True, "provider": "github"}
    assert service.listed_user_ids == ["user-1"]
    assert service.unlink_calls == [("user-1", ProviderId("github"))]
