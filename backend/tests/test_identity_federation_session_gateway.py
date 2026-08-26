from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.infrastructure import session_gateway as session_gateway_module
from app.joysafeter_identity_federation.infrastructure.session_gateway import JoySafeterAuthSessionGateway
from app.joysafeter_shared.ids import UserId

pytestmark = pytest.mark.no_db

_ACCESS_EXPIRES_AT = datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc)
_REFRESH_EXPIRES_AT = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
_USER_ID = UserId.from_public("user_00000000-0000-0000-0000-000000000001")


@dataclass
class _User:
    id: UserId
    is_active: bool


@dataclass(frozen=True)
class _TokenResult:
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class _FakeUserLoader:
    def __init__(self, user: _User | None, calls: list[str]) -> None:
        self._user = user
        self._calls = calls

    async def get_by_id(self, user_id: UserId) -> _User | None:
        self._calls.append(f"load:{user_id}")
        return self._user


def _fake_db() -> object:
    return object()


def _record_post_login(calls: list[str]):
    async def post_login(_db: object, user: _User, _ip_address: str) -> None:
        calls.append(f"post_login:{user.id}")

    return post_login


def _valid_token_result() -> _TokenResult:
    return _TokenResult(
        access_token="access",
        refresh_token="refresh",
        csrf_token="csrf",
        access_expires_at=_ACCESS_EXPIRES_AT,
        refresh_expires_at=_REFRESH_EXPIRES_AT,
    )


def _fake_auth_service(calls: list[str], token_result: object | None = None):
    class FakeAuthService:
        def __init__(self, _db: object) -> None:
            pass

        async def issue_login_tokens(self, user: _User) -> object:
            calls.append(f"issue:{user.id}")
            return _valid_token_result() if token_result is None else token_result

    return FakeAuthService


@pytest.mark.asyncio
async def test_session_gateway_runs_post_login_then_issues_session(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(session_gateway_module, "run_post_login_init", _record_post_login(calls))
    monkeypatch.setattr(session_gateway_module, "AuthService", _fake_auth_service(calls))
    gateway = JoySafeterAuthSessionGateway(
        _fake_db(),
        _FakeUserLoader(_User(id=_USER_ID, is_active=True), calls),
    )

    issued = await gateway.issue(user_id=_USER_ID, ip_address="203.0.113.10")

    assert calls == [f"load:{_USER_ID}", f"post_login:{_USER_ID}", f"issue:{_USER_ID}"]
    assert issued.access_token == "access"
    assert issued.refresh_token == "refresh"
    assert issued.csrf_token == "csrf"
    assert issued.access_expires_at is _ACCESS_EXPIRES_AT
    assert issued.refresh_expires_at is _REFRESH_EXPIRES_AT


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, _User(id=_USER_ID, is_active=False)])
async def test_session_gateway_rejects_missing_or_inactive_principals(user: _User | None) -> None:
    calls: list[str] = []
    gateway = JoySafeterAuthSessionGateway(_fake_db(), _FakeUserLoader(user, calls))

    with pytest.raises(FederationError) as exc_info:
        await gateway.issue(user_id=_USER_ID, ip_address="203.0.113.10")

    assert exc_info.value.code == "FEDERATION_PRINCIPAL_INVALID"
    assert exc_info.value.data == {}
    assert str(_USER_ID) not in exc_info.value.message
    assert calls == [f"load:{_USER_ID}"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_result",
    [
        pytest.param(
            {
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "access_expires_at": _ACCESS_EXPIRES_AT,
                "refresh_expires_at": _REFRESH_EXPIRES_AT,
            },
            id="missing-token-field",
        ),
        pytest.param(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "refresh_expires_at": _REFRESH_EXPIRES_AT,
            },
            id="missing-expiry-field",
        ),
        pytest.param("not-a-token-mapping", id="non-mapping-result"),
        pytest.param(
            {
                "access_token": 123,
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "access_expires_at": _ACCESS_EXPIRES_AT,
                "refresh_expires_at": _REFRESH_EXPIRES_AT,
            },
            id="wrong-token-type",
        ),
        pytest.param(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "access_expires_at": datetime(2026, 8, 15, 12, 30),
                "refresh_expires_at": _REFRESH_EXPIRES_AT,
            },
            id="naive-expiry",
        ),
        pytest.param(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "access_expires_at": _ACCESS_EXPIRES_AT,
                "refresh_expires_at": "2026-08-22T12:30:00Z",
            },
            id="wrong-expiry-type",
        ),
    ],
)
async def test_session_gateway_sanitizes_invalid_auth_session_contract(monkeypatch, token_result: object) -> None:
    calls: list[str] = []
    monkeypatch.setattr(session_gateway_module, "run_post_login_init", _record_post_login(calls))
    monkeypatch.setattr(session_gateway_module, "AuthService", _fake_auth_service(calls, token_result))
    gateway = JoySafeterAuthSessionGateway(
        _fake_db(),
        _FakeUserLoader(_User(id=_USER_ID, is_active=True), calls),
    )

    with pytest.raises(FederationError) as exc_info:
        await gateway.issue(user_id=_USER_ID, ip_address="203.0.113.10")

    assert exc_info.value.code == "FEDERATION_SESSION_ISSUE_FAILED"
    assert exc_info.value.message == "Unable to issue federated session"
    assert exc_info.value.data == {}
    assert calls == [f"load:{_USER_ID}", f"post_login:{_USER_ID}", f"issue:{_USER_ID}"]
