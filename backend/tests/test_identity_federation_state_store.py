import json
from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    CorrelationMethod,
    LoginAttempt,
    ProviderId,
)
from app.joysafeter_identity_federation.infrastructure.state_store import RedisLoginAttemptStore

pytestmark = pytest.mark.no_db


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.last_set: tuple[str, str, str, int] | None = None

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        self.last_set = (key, value, "NX" if nx else "", ex)
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str) -> str | None:
        assert numkeys == 1
        assert "GET" in script and "DEL" in script
        return self.values.pop(key, None)


def _attempt(attempt_id: str) -> LoginAttempt:
    created_at = datetime(2026, 8, 15, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    return LoginAttempt(
        id=attempt_id,
        provider_id=ProviderId("jd"),
        callback_url="/managed/quickstart",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/jd/callback",
        correlation_method=CorrelationMethod.SIGNED_COOKIE,
        retry_count=0,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
    )


@pytest.mark.asyncio
async def test_consume_returns_attempt_once() -> None:
    redis = _FakeRedis()
    store = RedisLoginAttemptStore(lambda: redis)
    attempt = _attempt("attempt-1")
    await store.create(attempt)

    assert await store.consume("attempt-1") == attempt
    assert await store.consume("attempt-1") is None


@pytest.mark.asyncio
async def test_create_uses_ten_minute_nx_redis_value() -> None:
    redis = _FakeRedis()
    store = RedisLoginAttemptStore(lambda: redis)

    await store.create(_attempt("attempt-1"))

    assert redis.last_set is not None
    key, serialized, condition, ttl = redis.last_set
    assert key == "identity_federation:attempt:attempt-1"
    assert condition == "NX"
    assert ttl == 600
    assert set(json.loads(serialized)) == {
        "id",
        "provider_id",
        "callback_url",
        "redirect_uri",
        "correlation_method",
        "retry_count",
        "created_at",
        "expires_at",
    }


@pytest.mark.asyncio
async def test_create_rejects_attempt_id_collisions() -> None:
    redis = _FakeRedis()
    store = RedisLoginAttemptStore(lambda: redis)
    await store.create(_attempt("attempt-1"))

    with pytest.raises(FederationError) as exc_info:
        await store.create(_attempt("attempt-1"))

    assert exc_info.value.code == "FEDERATION_ATTEMPT_COLLISION"


@pytest.mark.asyncio
async def test_missing_redis_fails_closed() -> None:
    store = RedisLoginAttemptStore(lambda: None)

    with pytest.raises(FederationError) as exc_info:
        await store.create(_attempt("attempt-1"))

    assert exc_info.value.code == "FEDERATION_STATE_STORE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_consume_invalid_json_removes_attempt_and_fails_closed() -> None:
    redis = _FakeRedis()
    store = RedisLoginAttemptStore(lambda: redis)
    redis.values["identity_federation:attempt:attempt-1"] = "not-json"

    with pytest.raises(FederationError) as exc_info:
        await store.consume("attempt-1")

    assert exc_info.value.code == "FEDERATION_ATTEMPT_INVALID"
    assert "identity_federation:attempt:attempt-1" not in redis.values
