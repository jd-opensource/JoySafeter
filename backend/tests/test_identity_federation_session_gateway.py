from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.infrastructure import session_gateway as session_gateway_module
from app.joysafeter_identity_federation.infrastructure.session_gateway import JoySafeterAuthSessionGateway

pytestmark = pytest.mark.no_db

_ACCESS_EXPIRES_AT = datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc)
_REFRESH_EXPIRES_AT = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)


@dataclass
class _User:
    id: str
    is_active: bool


class _FakeUserLoader:
    def __init__(self, user: _User | None, calls: list[str]) -> None:
        self._user = user
        self._calls = calls

    async def get_by_id(self, user_id: str) -> _User | None:
        self._calls.append(f"load:{user_id}")
        return self._user


def _fake_db() -> object:
    return object()


def _record_post_login(calls: list[str]):
    async def post_login(_db: object, user: _User, _ip_address: str) -> None:
        calls.append(f"post_login:{user.id}")

    return post_login


def _fake_auth_service(calls: list[str]):
    class FakeAuthService:
        def __init__(self, _db: object) -> None:
            pass

        async def issue_login_tokens(self, user: _User) -> dict[str, object]:
            calls.append(f"issue:{user.id}")
            return {
                "access_token": "access",
                "refresh_token": "refresh",
                "csrf_token": "csrf",
                "access_expires_at": _ACCESS_EXPIRES_AT,
                "refresh_expires_at": _REFRESH_EXPIRES_AT,
            }

    return FakeAuthService


@pytest.mark.asyncio
async def test_session_gateway_runs_post_login_then_issues_session(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(session_gateway_module, "run_post_login_init", _record_post_login(calls))
    monkeypatch.setattr(session_gateway_module, "AuthService", _fake_auth_service(calls))
    gateway = JoySafeterAuthSessionGateway(
        _fake_db(),
        _FakeUserLoader(_User(id="user-1", is_active=True), calls),
    )

    issued = await gateway.issue(user_id="user-1", ip_address="203.0.113.10")

    assert calls == ["load:user-1", "post_login:user-1", "issue:user-1"]
    assert issued.access_token == "access"
    assert issued.refresh_token == "refresh"
    assert issued.csrf_token == "csrf"
    assert issued.access_expires_at is _ACCESS_EXPIRES_AT
    assert issued.refresh_expires_at is _REFRESH_EXPIRES_AT


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, _User(id="user-1", is_active=False)])
async def test_session_gateway_rejects_missing_or_inactive_principals(user: _User | None) -> None:
    calls: list[str] = []
    gateway = JoySafeterAuthSessionGateway(_fake_db(), _FakeUserLoader(user, calls))

    with pytest.raises(FederationError) as exc_info:
        await gateway.issue(user_id="user-1", ip_address="203.0.113.10")

    assert exc_info.value.code == "FEDERATION_PRINCIPAL_INVALID"
    assert exc_info.value.data == {}
    assert "user-1" not in exc_info.value.message
    assert calls == ["load:user-1"]
