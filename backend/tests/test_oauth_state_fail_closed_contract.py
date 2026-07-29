"""OAuth `state` validation must fail CLOSED when it cannot be confirmed.

`state` is the OAuth login-CSRF nonce: it is minted, stored server-side in Redis,
and single-use (deleted on read). `oauth.py::_validate_state` returns the stored
state dict on success and `None` to signal "reject" — the caller treats `None`
as invalid-state and aborts the login (`oauth.py:230`).

The bug: when Redis is unavailable or the lookup raises, `_validate_state`
returned `{}` (a truthy, non-`None` value), which the caller does NOT treat as a
rejection. That turns an infrastructure outage into a silent disabling of the
login-CSRF control — the state nonce is no longer verified against the store.
A security nonce store being down must fail closed (reject the login), never
fail open (accept an unverifiable state).
"""

import json

import pytest

from app.joysafeter_api.api.v1.oauth import _validate_state
from app.joysafeter_shared.cache.redis import RedisClient

pytestmark = pytest.mark.no_db


class _FakeOAuthSettings:
    default_redirect_url = "https://app.example.com/managed/quickstart"


class _FakeOAuthConfig:
    settings = _FakeOAuthSettings()


@pytest.mark.asyncio
async def test_validate_state_fails_closed_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(RedisClient, "is_available", classmethod(lambda cls: False))

    state_data, callback_url = await _validate_state("forged-or-stale-state", _FakeOAuthConfig())

    assert state_data is None, "Redis-down must reject the state (fail closed), not return {}"
    assert callback_url == _FakeOAuthSettings.default_redirect_url


@pytest.mark.asyncio
async def test_validate_state_fails_closed_when_redis_get_raises(monkeypatch):
    monkeypatch.setattr(RedisClient, "is_available", classmethod(lambda cls: True))

    async def _boom(cls, key):
        raise RuntimeError("redis connection reset")

    monkeypatch.setattr(RedisClient, "get", classmethod(_boom))

    state_data, callback_url = await _validate_state("forged-or-stale-state", _FakeOAuthConfig())

    assert state_data is None, "a Redis lookup error must reject the state (fail closed), not return {}"
    assert callback_url == _FakeOAuthSettings.default_redirect_url


@pytest.mark.asyncio
async def test_validate_state_returns_data_for_valid_state(monkeypatch):
    """Happy path must keep working: a stored, matching state resolves and is consumed."""
    stored = {"provider": "google", "callback_url": "/managed/dashboard", "redirect_uri": "https://x/cb"}
    deleted: list[str] = []

    monkeypatch.setattr(RedisClient, "is_available", classmethod(lambda cls: True))

    async def _get(cls, key):
        assert key == "oauth_state:good-state"
        return json.dumps(stored)

    async def _delete(cls, key):
        deleted.append(key)
        return True

    monkeypatch.setattr(RedisClient, "get", classmethod(_get))
    monkeypatch.setattr(RedisClient, "delete", classmethod(_delete))

    state_data, callback_url = await _validate_state("good-state", _FakeOAuthConfig())

    assert state_data == stored
    assert callback_url == "/managed/dashboard"
    assert deleted == ["oauth_state:good-state"], "a valid state must be single-use (deleted on read)"


@pytest.mark.asyncio
async def test_validate_state_rejects_missing_state(monkeypatch):
    """A state absent from the store (expired/forged) must reject with None."""
    monkeypatch.setattr(RedisClient, "is_available", classmethod(lambda cls: True))

    async def _get(cls, key):
        return None

    monkeypatch.setattr(RedisClient, "get", classmethod(_get))

    state_data, callback_url = await _validate_state("not-in-store", _FakeOAuthConfig())

    assert state_data is None
    assert callback_url == _FakeOAuthSettings.default_redirect_url
