from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    ActiveProvider,
    Authenticated,
    CallbackContext,
    CorrelationMethod,
    LoginAttempt,
    OAuth2ProviderSettings,
    ProtocolId,
    ProviderId,
    RequestContext,
)
from app.joysafeter_identity_federation.infrastructure.protocols.oauth2 import OAuth2Adapter

pytestmark = pytest.mark.no_db

ClientFactory = Callable[[], httpx.AsyncClient]


def _github_provider(
    *,
    auth_method: str = "client_secret_post",
    userinfo_headers: dict[str, str] | None = None,
    user_mapping: dict[str, str] | None = None,
) -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("github"),
        display_name="GitHub",
        icon="github",
        protocol=ProtocolId.OAUTH2,
        settings=OAuth2ProviderSettings(
            client_id="github-client",
            client_secret="github-secret",
            authorize_url="https://github.example/authorize",
            token_url="https://github.example/token",
            userinfo_url="https://api.github.example/user",
            issuer=None,
            scope="read:user user:email",
            user_mapping=user_mapping
            or {
                "id": "id",
                "email": "email",
                "name": "name",
                "avatar": "avatar_url",
            },
            token_endpoint_auth_method=auth_method,
            userinfo_headers=userinfo_headers or {"Accept": "application/vnd.github+json"},
        ),
    )


def _oidc_provider() -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("oidc"),
        display_name="OIDC",
        icon="key",
        protocol=ProtocolId.OAUTH2,
        settings=OAuth2ProviderSettings(
            client_id="oidc-client",
            client_secret="oidc-secret",
            authorize_url=None,
            token_url=None,
            userinfo_url=None,
            issuer="https://issuer.example",
            scope="openid email profile",
            user_mapping={
                "id": "sub",
                "email": "email",
                "name": "name",
                "avatar": "picture",
            },
        ),
    )


def _attempt(attempt_id: str) -> LoginAttempt:
    now = datetime.now(UTC)
    return LoginAttempt(
        id=attempt_id,
        provider_id=ProviderId("oidc"),
        callback_url="/managed/quickstart",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/oidc/callback",
        correlation_method=CorrelationMethod.OAUTH_STATE,
        retry_count=0,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def _request_context() -> RequestContext:
    return RequestContext(
        base_url="https://api.example.com",
        request_url="https://api.example.com/api/v1/auth/oauth/oidc",
        client_ip="192.0.2.1",
        headers={},
        cookies={},
    )


def _callback_context(*, query: dict[str, str]) -> CallbackContext:
    return CallbackContext(
        base_url="https://api.example.com",
        request_url="https://api.example.com/api/v1/auth/oauth/oidc/callback",
        client_ip="192.0.2.1",
        headers={},
        cookies={},
        query=query,
    )


def _unused_client_factory() -> httpx.AsyncClient:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP client must not be used")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_factory(responses: dict[str, tuple[int, object]]) -> ClientFactory:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            response_key = "token"
        elif request.url.path.endswith("/user/emails"):
            response_key = "emails"
        elif request.url.path.endswith("/userinfo") or request.url.path.endswith("/user"):
            response_key = "userinfo"
        elif request.url.path.endswith("/.well-known/openid-configuration"):
            response_key = "discovery"
        else:
            raise AssertionError(f"Unexpected request path: {request.url.path}")
        status_code, payload = responses[response_key]
        return httpx.Response(status_code, json=payload)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_oidc_client() -> httpx.AsyncClient:
    return _client_factory(
        {
            "discovery": (
                200,
                {
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/token",
                    "userinfo_endpoint": "https://issuer.example/userinfo",
                },
            ),
            "token": (200, {"access_token": "access-token", "refresh_token": "refresh-token"}),
            "userinfo": (
                200,
                {
                    "sub": "subject-1",
                    "email": "User@Example.com",
                    "email_verified": True,
                    "name": "Example User",
                    "picture": "https://images.example/avatar.png",
                    "roles": ["admin"],
                },
            ),
        }
    )()


def _github_client_factory() -> ClientFactory:
    return _client_factory(
        {
            "token": (200, {"access_token": "access-token"}),
            "userinfo": (
                200,
                {
                    "id": 42,
                    "email": "unverified@example.com",
                    "name": "GitHub User",
                    "avatar_url": "https://images.example/github.png",
                },
            ),
            "emails": (
                200,
                [
                    {"email": "unverified-primary@example.com", "primary": True, "verified": False},
                    {"email": "verified-secondary@example.com", "primary": False, "verified": True},
                    {"email": "verified@example.com", "primary": True, "verified": True},
                ],
            ),
        }
    )


@pytest.mark.asyncio
async def test_begin_login_uses_attempt_id_as_state() -> None:
    adapter = OAuth2Adapter(client_factory=_unused_client_factory)
    action = await adapter.begin_login(_github_provider(), _attempt("attempt-1"), _request_context())

    parsed = parse_qs(urlparse(action.authorization_url).query)
    assert parsed["state"] == ["attempt-1"]
    assert parsed["redirect_uri"] == [_attempt("attempt-1").redirect_uri]


@pytest.mark.asyncio
async def test_begin_login_replaces_reserved_authorization_query_parameters() -> None:
    provider = _github_provider()
    settings = provider.settings
    assert isinstance(settings, OAuth2ProviderSettings)
    provider = replace(
        provider,
        settings=replace(
            settings,
            authorize_url="https://github.example/authorize?state=attacker&client_id=attacker",
        ),
    )

    action = await OAuth2Adapter(client_factory=_unused_client_factory).begin_login(
        provider, _attempt("attempt-1"), _request_context()
    )

    parsed = parse_qs(urlparse(action.authorization_url).query)
    assert parsed["state"] == ["attempt-1"]
    assert parsed["client_id"] == ["github-client"]


def test_extract_attempt_id_requires_state() -> None:
    adapter = OAuth2Adapter(client_factory=_unused_client_factory)

    with pytest.raises(FederationError) as exc_info:
        adapter.extract_attempt_id(_callback_context(query={}))

    assert exc_info.value.code == "FEDERATION_ATTEMPT_INVALID"


@pytest.mark.asyncio
async def test_oidc_email_verified_claim_controls_principal() -> None:
    adapter = OAuth2Adapter(client_factory=_mock_oidc_client)
    outcome = await adapter.complete_login(
        _oidc_provider(),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.subject == "subject-1"
    assert outcome.principal.email_verified is True


@pytest.mark.parametrize(
    ("query", "expected_code"),
    [
        ({"state": "attempt-1", "error": "access_denied"}, "FEDERATION_UPSTREAM_DENIED"),
        ({"state": "attempt-1"}, "FEDERATION_CALLBACK_INVALID"),
    ],
)
@pytest.mark.asyncio
async def test_callback_query_failures_are_typed(query: dict[str, str], expected_code: str) -> None:
    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_unused_client_factory).complete_login(
            _github_provider(),
            _attempt("attempt-1"),
            _callback_context(query=query),
        )

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("responses", "expected_code"),
    [
        ({"token": (502, {})}, "FEDERATION_UPSTREAM_UNAVAILABLE"),
        (
            {"token": (200, {"access_token": "access-token"}), "userinfo": (503, {})},
            "FEDERATION_UPSTREAM_UNAVAILABLE",
        ),
    ],
)
@pytest.mark.asyncio
async def test_upstream_failures_do_not_leak_response_data(
    responses: dict[str, tuple[int, object]], expected_code: str
) -> None:
    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_client_factory(responses)).complete_login(
            _github_provider(),
            _attempt("attempt-1"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == expected_code
    assert "access_token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_github_primary_verified_email_is_authoritative() -> None:
    outcome = await OAuth2Adapter(client_factory=_github_client_factory()).complete_login(
        _github_provider(),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.email == "verified@example.com"
    assert outcome.principal.email_verified is True


def _counting_discovery_transport() -> tuple[httpx.MockTransport, dict[str, int]]:
    calls = {"discovery": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/.well-known/openid-configuration")
        calls["discovery"] += 1
        return httpx.Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example/authorize",
                "token_endpoint": "https://issuer.example/token",
                "userinfo_endpoint": "https://issuer.example/userinfo",
            },
        )

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_oidc_discovery_is_cached_by_issuer() -> None:
    transport, calls = _counting_discovery_transport()
    adapter = OAuth2Adapter(client_factory=lambda: httpx.AsyncClient(transport=transport))

    await adapter.begin_login(_oidc_provider(), _attempt("attempt-1"), _request_context())
    await adapter.begin_login(_oidc_provider(), _attempt("attempt-2"), _request_context())

    assert calls["discovery"] == 1


@pytest.mark.parametrize("auth_method", ["client_secret_basic", "client_secret_post"])
@pytest.mark.asyncio
async def test_token_exchange_supports_configured_client_auth_method(auth_method: str) -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        if request.url.path.endswith("/token"):
            captured_request = request
            return httpx.Response(200, json={"access_token": "access-token"})
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json={"id": "42"})
        if request.url.path.endswith("/user/emails"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await OAuth2Adapter(client_factory=factory).complete_login(
        _github_provider(auth_method=auth_method),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert captured_request is not None
    form = parse_qs(captured_request.content.decode())
    if auth_method == "client_secret_basic":
        assert captured_request.headers["Authorization"] == "Basic Z2l0aHViLWNsaWVudDpnaXRodWItc2VjcmV0"
        assert "client_id" not in form
        assert "client_secret" not in form
    else:
        assert "Authorization" not in captured_request.headers
        assert form["client_id"] == ["github-client"]
        assert form["client_secret"] == ["github-secret"]


@pytest.mark.asyncio
async def test_configured_mapping_and_userinfo_headers_shape_sanitized_claims() -> None:
    captured_headers: httpx.Headers | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_headers
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": "id-token",
                },
            )
        if request.url.path.endswith("/user"):
            captured_headers = request.headers
            return httpx.Response(
                200,
                json={
                    "external_id": "subject-42",
                    "mail": "mapped@example.com",
                    "label": "Mapped User",
                    "photo": "https://images.example/mapped.png",
                    "access_token": "userinfo-token",
                    "role": "admin",
                },
            )
        if request.url.path.endswith("/user/emails"):
            return httpx.Response(
                200,
                json=[{"email": "verified@example.com", "primary": True, "verified": True}],
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    provider = _github_provider(
        userinfo_headers={"Accept": "application/custom+json", "X-Provider": "github"},
        user_mapping={
            "id": "external_id",
            "email": "mail",
            "name": "label",
            "avatar": "photo",
        },
    )
    outcome = await OAuth2Adapter(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ).complete_login(
        provider,
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert captured_headers is not None
    assert captured_headers["Accept"] == "application/custom+json"
    assert captured_headers["X-Provider"] == "github"
    assert captured_headers["Authorization"] == "Bearer access-token"
    assert outcome.principal.claims == {
        "id": "subject-42",
        "email": "verified@example.com",
        "name": "Mapped User",
        "avatar": "https://images.example/mapped.png",
    }
    assert "access_token" not in outcome.principal.claims
    assert "refresh_token" not in outcome.principal.claims
    with pytest.raises(TypeError):
        outcome.principal.claims["role"] = "owner"


@pytest.mark.asyncio
async def test_mapped_claims_exclude_nested_mutable_values() -> None:
    factory = _client_factory(
        {
            "discovery": (
                200,
                {
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/token",
                    "userinfo_endpoint": "https://issuer.example/userinfo",
                },
            ),
            "token": (200, {"access_token": "access-token"}),
            "userinfo": (
                200,
                {
                    "sub": "subject-1",
                    "email": "user@example.com",
                    "email_verified": True,
                    "name": {"mutable": True},
                    "picture": ["https://images.example/avatar.png"],
                },
            ),
        }
    )

    outcome = await OAuth2Adapter(client_factory=factory).complete_login(
        _oidc_provider(),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.claims == {"id": "subject-1", "email": "user@example.com"}
    assert outcome.principal.display_name is None
    assert outcome.principal.avatar_url is None


@pytest.mark.asyncio
async def test_unsafe_configured_endpoint_is_rejected_before_http() -> None:
    provider = _github_provider()
    settings = provider.settings
    assert isinstance(settings, OAuth2ProviderSettings)
    unsafe_provider = ActiveProvider(
        id=provider.id,
        display_name=provider.display_name,
        icon=provider.icon,
        protocol=provider.protocol,
        settings=OAuth2ProviderSettings(
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            authorize_url=settings.authorize_url,
            token_url="http://169.254.169.254/latest/token",
            userinfo_url=settings.userinfo_url,
            issuer=settings.issuer,
            scope=settings.scope,
            user_mapping=settings.user_mapping,
            token_endpoint_auth_method=settings.token_endpoint_auth_method,
            userinfo_headers=settings.userinfo_headers,
        ),
    )

    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_unused_client_factory).complete_login(
            unsafe_provider,
            _attempt("attempt-1"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_private_configured_endpoint_is_rejected_before_http() -> None:
    provider = _github_provider()
    settings = provider.settings
    assert isinstance(settings, OAuth2ProviderSettings)
    provider = replace(
        provider,
        settings=replace(settings, token_url="http://10.0.0.1/token"),
    )

    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_unused_client_factory).complete_login(
            provider,
            _attempt("attempt-1"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_local_provider_accepts_configured_http_loopback_endpoint() -> None:
    provider = _github_provider()
    settings = provider.settings
    assert isinstance(settings, OAuth2ProviderSettings)
    provider = replace(
        provider,
        id=ProviderId("local"),
        settings=replace(settings, authorize_url="http://127.0.0.1:9090/authorize"),
    )

    action = await OAuth2Adapter(client_factory=_unused_client_factory).begin_login(
        provider, _attempt("attempt-1"), _request_context()
    )

    assert action.authorization_url.startswith("http://127.0.0.1:9090/authorize?")


@pytest.mark.asyncio
async def test_callback_state_must_match_attempt() -> None:
    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_unused_client_factory).complete_login(
            _github_provider(),
            _attempt("attempt-1"),
            _callback_context(query={"state": "different-attempt", "code": "code-1"}),
        )

    assert exc_info.value.code == "FEDERATION_ATTEMPT_INVALID"
