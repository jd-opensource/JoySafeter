from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services import joysafeter_auth_service as auth_service_module
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService
from app.joysafeter_shared.ids import UserId

pytestmark = pytest.mark.no_db

_ACCESS_EXPIRES_AT = datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc)
_REFRESH_EXPIRES_AT = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
TEST_USER_ID = UserId.new()


class _TokenIssuingAuthService(AuthService):
    def __init__(self) -> None:
        pass

    async def _issue_jwt_tokens(self, user_id: UserId) -> tuple[str, str, str, datetime, datetime]:
        assert user_id == TEST_USER_ID
        return "access", "refresh", "csrf", _ACCESS_EXPIRES_AT, _REFRESH_EXPIRES_AT


class _FakeLogger:
    def __init__(self) -> None:
        self.bound: dict | None = None
        self.messages: list[tuple[str, str]] = []

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def debug(self, message: str) -> None:
        self.messages.append(("debug", message))


class _FailingDeleteRedis:
    async def delete(self, key: str) -> None:
        raise RuntimeError("redis unavailable")


class _SessionService:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    async def invalidate_session(self, token: str) -> None:
        self.invalidated.append(token)


@pytest.mark.asyncio
async def test_issue_login_tokens_exposes_calculated_timezone_aware_expiries() -> None:
    user = SimpleNamespace(
        id=TEST_USER_ID,
        email="user@example.com",
        name="User",
        image=None,
        email_verified=True,
        is_super_user=False,
        created_at=None,
        updated_at=None,
    )

    token_result = await _TokenIssuingAuthService().issue_login_tokens(user)

    assert token_result.user is user
    assert token_result.access_token == "access"
    assert token_result.refresh_token == "refresh"
    assert token_result.csrf_token == "csrf"
    assert token_result.token_type == "bearer"
    assert token_result.access_expires_at is _ACCESS_EXPIRES_AT
    assert token_result.refresh_expires_at is _REFRESH_EXPIRES_AT
    assert token_result.expires_in == 0
    with pytest.raises(FrozenInstanceError):
        token_result.access_token = "changed"
    assert _ACCESS_EXPIRES_AT.utcoffset() is not None
    assert _REFRESH_EXPIRES_AT.utcoffset() is not None


@pytest.mark.asyncio
async def test_refresh_token_rotate_failure_logs_structured_boundary_error(monkeypatch) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr(auth_service_module, "logger", fake_logger)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.is_available",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: _FailingDeleteRedis()),
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.set",
        staticmethod(lambda key, value, expire: None),
    )
    service = object.__new__(AuthService)
    service.session_service = _SessionService()

    await service._rotate_refresh_token("secret-refresh-token", TEST_USER_ID)

    assert service.session_service.invalidated == ["refresh:secret-refresh-token"]
    assert fake_logger.messages == [("debug", "Failed to rotate refresh token in Redis")]
    assert fake_logger.bound is not None
    error = fake_logger.bound["error"]
    assert error["code"] == "AUTH_REFRESH_TOKEN_REDIS_ROTATE_FAILED"
    assert error["data"] == {
        "boundary": "auth_service",
        "operation": "rotate_refresh_token",
        "user_id": str(TEST_USER_ID),
    }
    assert "secret-refresh-token" not in str(error)
