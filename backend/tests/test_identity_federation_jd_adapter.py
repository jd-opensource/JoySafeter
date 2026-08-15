import ast
import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    ActiveProvider,
    Authenticated,
    CallbackContext,
    CorrelationMethod,
    JDSSOProviderSettings,
    LoginAttempt,
    ProtocolId,
    ProviderId,
    RequestContext,
    RestartAuthorization,
)
from app.joysafeter_identity_federation.infrastructure.correlation import SignedCorrelationCodec
from app.joysafeter_identity_federation.infrastructure.protocols import oauth2 as oauth2_module
from app.joysafeter_identity_federation.infrastructure.protocols.jd_sso import JDSSOAdapter

pytestmark = pytest.mark.no_db

ClientFactory = Callable[[], httpx.AsyncClient]
_NOW = 1_786_748_000.0


class _UnknownProxyTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, request=request)


@pytest.fixture(autouse=True)
def _resolve_test_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oauth2_module,
        "_resolve_endpoint_addresses",
        lambda _hostname, _port: ("93.184.216.34",),
    )


def _codec() -> SignedCorrelationCodec:
    return SignedCorrelationCodec(
        secret=b"application-secret",
        cookie_name="joysafeter_federation_attempt",
    )


def _signed(attempt_id: str) -> str:
    return _codec().sign(attempt_id, expires_at=int(_NOW) + 600)


def _jd_provider(*, userinfo_url: str = "https://sso.jd.com/verifyTicket") -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("jd"),
        display_name="JD SSO",
        icon="building",
        protocol=ProtocolId.JD_SSO,
        settings=JDSSOProviderSettings(
            client_id="jd-client",
            client_secret="jd-secret",
            authorize_url="https://sso.jd.com/login",
            userinfo_url=userinfo_url,
            scope="openid email",
            user_mapping={
                "id": "userId",
                "email": "email",
                "name": "username",
                "avatar": "avatar",
            },
        ),
    )


def _attempt(attempt_id: str) -> LoginAttempt:
    now = datetime.fromtimestamp(_NOW, UTC)
    return LoginAttempt(
        id=attempt_id,
        provider_id=ProviderId("jd"),
        callback_url="/managed/quickstart",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/jd/callback",
        correlation_method=CorrelationMethod.SIGNED_COOKIE,
        retry_count=0,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def _request_context() -> RequestContext:
    return RequestContext(
        base_url="https://api.example.com",
        request_url="https://api.example.com/api/v1/auth/oauth/jd",
        client_ip="192.0.2.1",
        headers={},
        cookies={},
    )


def _callback_context(
    *,
    query: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> CallbackContext:
    return CallbackContext(
        base_url="https://api.example.com",
        request_url="https://api.example.com/api/v1/auth/oauth/jd/callback",
        client_ip="192.0.2.44",
        headers={"X-Forwarded-For": "198.51.100.10"},
        cookies=cookies or {},
        query=query or {},
    )


def _callback_context_with_ticket(ticket: str) -> CallbackContext:
    return _callback_context(
        cookies={
            "joysafeter_federation_attempt": _signed("attempt-1"),
            "sso.jd.com": ticket,
        }
    )


def _unused_client_factory() -> httpx.AsyncClient:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP client must not be used")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_factory(response: object, *, status_code: int = 200) -> ClientFactory:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _adapter(
    *,
    response: object | None = None,
    client_factory: ClientFactory | None = None,
) -> JDSSOAdapter:
    if client_factory is None:
        client_factory = _unused_client_factory if response is None else _client_factory(response)
    return JDSSOAdapter(
        correlation_codec=_codec(),
        client_factory=client_factory,
        now=lambda: _NOW,
    )


def test_jd_signature_matches_reference_vector() -> None:
    assert (
        JDSSOAdapter.compute_signature(
            client_secret="secret",
            timestamp_ms=1_700_000_000_000,
            ticket="ticket",
        )
        == hashlib.md5(b"secret1700000000000ticket").hexdigest()
    )


@pytest.mark.asyncio
async def test_begin_login_sets_signed_correlation_cookie() -> None:
    action = await _adapter().begin_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _request_context(),
    )

    assert action.authorization_url.startswith("https://sso.jd.com/")
    query = parse_qs(urlparse(action.authorization_url).query)
    assert query == {
        "client_id": ["jd-client"],
        "redirect_uri": [_attempt("attempt-1").redirect_uri],
        "response_type": ["code"],
        "scope": ["openid email"],
    }
    assert action.correlation_cookie is not None
    assert action.correlation_cookie.name == "joysafeter_federation_attempt"
    assert action.correlation_cookie.max_age_seconds == 600
    assert _codec().verify(action.correlation_cookie.value, now_epoch=int(_NOW)) == "attempt-1"


def test_extract_attempt_id_verifies_signed_cookie() -> None:
    context = _callback_context(
        cookies={"joysafeter_federation_attempt": _signed("attempt-1")},
    )

    assert _adapter().extract_attempt_id(context) == "attempt-1"


@pytest.mark.parametrize(
    "context",
    [
        _callback_context(query={"state": "attempt-1"}),
        _callback_context(cookies={"joysafeter_federation_attempt": "tampered"}),
    ],
)
def test_extract_attempt_id_never_falls_back_to_query_state(context: CallbackContext) -> None:
    with pytest.raises(FederationError) as exc_info:
        _adapter().extract_attempt_id(context)

    assert exc_info.value.code == "FEDERATION_CORRELATION_INVALID"


@pytest.mark.asyncio
async def test_missing_jd_session_requests_one_bounded_restart() -> None:
    outcome = await _adapter().complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context(
            query={},
            cookies={"joysafeter_federation_attempt": _signed("attempt-1")},
        ),
    )

    assert outcome == RestartAuthorization(reason="jd_session_missing")


@pytest.mark.asyncio
async def test_blank_jd_session_is_a_typed_malformed_callback() -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter().complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context(
                cookies={
                    "joysafeter_federation_attempt": _signed("attempt-1"),
                    "sso.jd.com": "   ",
                }
            ),
        )

    assert exc_info.value.code == "FEDERATION_CALLBACK_INVALID"


@pytest.mark.asyncio
async def test_correlation_attempt_must_match_consumed_attempt() -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter().complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context(
                cookies={
                    "joysafeter_federation_attempt": _signed("different-attempt"),
                    "sso.jd.com": "ticket",
                }
            ),
        )

    assert exc_info.value.code == "FEDERATION_ATTEMPT_INVALID"


@pytest.mark.asyncio
async def test_verify_ticket_uses_exact_protocol_parameters() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={"REQ_FLAG": True, "REQ_DATA": {"userId": "42", "username": "zhangsan"}},
        )

    outcome = await _adapter(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ).complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert isinstance(outcome, Authenticated)
    assert captured_request is not None
    assert dict(captured_request.url.params) == {
        "ticket": "ticket",
        "url": "https://api.example.com/api/v1/auth/oauth/jd/callback",
        "ip": "192.0.2.44",
        "app": "jd-client",
        "time": str(int(_NOW * 1000)),
        "sign": JDSSOAdapter.compute_signature(
            client_secret="jd-secret",
            timestamp_ms=int(_NOW * 1000),
            ticket="ticket",
        ),
    }


@pytest.mark.asyncio
async def test_derived_jd_email_is_unverified() -> None:
    outcome = await _adapter(
        response={"REQ_FLAG": True, "REQ_DATA": {"userId": "42", "username": "zhangsan"}}
    ).complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.subject == "42"
    assert outcome.principal.email == "zhangsan@jd.com"
    assert outcome.principal.email_verified is False
    assert outcome.principal.display_name == "zhangsan"


@pytest.mark.asyncio
async def test_jd_mapping_keeps_only_configured_scalar_identity_claims() -> None:
    outcome = await _adapter(
        response={
            "REQ_FLAG": True,
            "REQ_DATA": {
                "userId": 42,
                "email": "USER@JD.COM",
                "username": "Zhang San",
                "avatar": "https://images.example/avatar.png",
                "credential": "must-not-leak",
                "groups": ["admin"],
            },
        }
    ).complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.email == "user@jd.com"
    assert outcome.principal.email_verified is False
    assert outcome.principal.avatar_url == "https://images.example/avatar.png"
    assert outcome.principal.claims == {
        "id": 42,
        "email": "USER@JD.COM",
        "name": "Zhang San",
        "avatar": "https://images.example/avatar.png",
    }


@pytest.mark.parametrize(
    "response",
    [
        {"REQ_FLAG": True, "REQ_DATA": []},
        {"REQ_FLAG": True, "REQ_DATA": {"userId": "", "username": "zhangsan"}},
        {"REQ_FLAG": "true", "REQ_DATA": {"userId": "42"}},
        [],
    ],
)
@pytest.mark.asyncio
async def test_malformed_jd_responses_raise_typed_errors(response: object) -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter(response=response).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("ticket"),
        )

    assert exc_info.value.code in {
        "FEDERATION_PRINCIPAL_INVALID",
        "FEDERATION_UPSTREAM_UNAVAILABLE",
    }


@pytest.mark.asyncio
async def test_jd_denial_does_not_leak_req_data_or_ticket() -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter(
            response={
                "REQ_FLAG": False,
                "REQ_DATA": {"reason": "sensitive denial", "ticket": "secret-ticket"},
            }
        ).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("secret-ticket"),
        )

    assert exc_info.value.code == "FEDERATION_UPSTREAM_DENIED"
    assert exc_info.value.data == {}
    assert "sensitive denial" not in str(exc_info.value)
    assert "secret-ticket" not in str(exc_info.value)


@pytest.mark.parametrize("status_code", [400, 500])
@pytest.mark.asyncio
async def test_jd_http_failures_are_sanitized(status_code: int) -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter(
            client_factory=_client_factory(
                {"REQ_DATA": {"ticket": "secret-ticket"}},
                status_code=status_code,
            )
        ).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("secret-ticket"),
        )

    assert exc_info.value.code == "FEDERATION_UPSTREAM_UNAVAILABLE"
    assert exc_info.value.data == {}
    assert "secret-ticket" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_jd_request_pins_ip_preserves_host_sni_and_enforces_timeout() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"REQ_FLAG": True, "REQ_DATA": {"userId": "42"}})

    await _adapter(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
            timeout=None,
        )
    ).complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert captured_request is not None
    assert captured_request.url.host == "93.184.216.34"
    assert captured_request.headers["Host"] == "sso.jd.com"
    assert captured_request.extensions["sni_hostname"] == "sso.jd.com"
    timeout = captured_request.extensions["timeout"]
    assert all(value is not None and 0 < value <= 10 for value in timeout.values())


@pytest.mark.asyncio
async def test_jd_redirect_is_not_followed() -> None:
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"}, request=request)

    with pytest.raises(FederationError) as exc_info:
        await _adapter(
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=True,
            )
        ).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("secret-ticket"),
        )

    assert exc_info.value.code == "FEDERATION_UPSTREAM_UNAVAILABLE"
    assert request_count == 1


@pytest.mark.asyncio
async def test_jd_rejects_unapproved_http_client_transport() -> None:
    with pytest.raises(FederationError) as exc_info:
        await _adapter(client_factory=lambda: httpx.AsyncClient(transport=_UnknownProxyTransport())).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("ticket"),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_jd_runtime_loopback_requires_compiled_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        oauth2_module,
        "_resolve_endpoint_addresses",
        lambda _hostname, _port: ("127.0.0.1",),
    )

    with pytest.raises(FederationError) as exc_info:
        await _adapter(response={"REQ_FLAG": True, "REQ_DATA": {"userId": "42"}}).complete_login(
            _jd_provider(userinfo_url="http://127.0.0.1:9090/verifyTicket"),
            _attempt("attempt-1"),
            _callback_context_with_ticket("ticket"),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_jd_runtime_loopback_honors_compiled_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        oauth2_module,
        "_resolve_endpoint_addresses",
        lambda _hostname, _port: ("127.0.0.1",),
    )
    provider = replace(
        _jd_provider(userinfo_url="http://127.0.0.1:9090/verifyTicket"),
        allow_http_loopback=True,
    )

    outcome = await _adapter(response={"REQ_FLAG": True, "REQ_DATA": {"userId": "42"}}).complete_login(
        provider,
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert isinstance(outcome, Authenticated)


@pytest.mark.asyncio
async def test_jd_hard_deadline_covers_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oauth2_module, "_REQUEST_DEADLINE_SECONDS", 0.01)

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"REQ_FLAG": True, "REQ_DATA": {"userId": "42"}})

    with pytest.raises(FederationError) as exc_info:
        await _adapter(client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))).complete_login(
            _jd_provider(),
            _attempt("attempt-1"),
            _callback_context_with_ticket("ticket"),
        )

    assert exc_info.value.code == "FEDERATION_UPSTREAM_UNAVAILABLE"


def test_jd_adapter_has_no_auth_database_session_or_api_imports() -> None:
    adapter_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "joysafeter_identity_federation"
        / "infrastructure"
        / "protocols"
        / "jd_sso.py"
    )
    imported_roots: set[str] = set()
    for node in ast.walk(ast.parse(adapter_path.read_text())):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module)

    assert not {
        module
        for module in imported_roots
        if any(
            forbidden in module.lower()
            for forbidden in ("fastapi", "sqlalchemy", "redis", "jwt", "auth_service", "database")
        )
    }
