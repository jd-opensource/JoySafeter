"""The unauthenticated readiness endpoint must not leak internal fleet state.

`GET /api/v1/health` (and `/ready`) is reachable without authentication so load
balancers can probe it. It must expose only up/down/degraded booleans — never
the orchestrator fleet topology (live/stale counts, heartbeat/expiry timestamps)
or raw database exception text, which would let an untrusted tenant fingerprint
the fleet and time attacks on low-capacity windows.
"""

import json

import pytest

from app.joysafeter_api.api.v1.health import health_ready

pytestmark = pytest.mark.no_db


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, *args, **kwargs):
        return None


def _patch_probes(monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr("app.joysafeter_shared.cache.redis.RedisClient.get_client", staticmethod(lambda: None))


@pytest.mark.asyncio
async def test_health_ready_does_not_leak_fleet_topology(monkeypatch):
    _patch_probes(monkeypatch)

    resp = await health_ready()
    body_text = resp.body.decode()

    for leaked in ("live_orchestrators", "stale_orchestrators", "newest_heartbeat_at", "newest_expires_at"):
        assert leaked not in body_text, f"unauthenticated /ready must not expose {leaked}"

    body = json.loads(body_text)
    assert body["status"] == "ok"
    assert body["checks"]["postgres"] == "up"
    assert body["checks"]["redis"] == "up"
    assert "cluster_membership" not in body["checks"]


@pytest.mark.asyncio
async def test_health_ready_does_not_leak_db_error_text(monkeypatch):
    class _FailingSession(_FakeSession):
        async def execute(self, *args, **kwargs):
            raise RuntimeError("connection refused on host db-primary:5432")

    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", lambda: _FailingSession())
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    resp = await health_ready()
    body_text = resp.body.decode()

    assert "does not exist" not in body_text, "raw DB exception text must not reach an anonymous caller"
    assert "db-primary:5432" not in body_text
    body = json.loads(body_text)
    assert resp.status_code == 503
    assert body["checks"]["postgres"] == "down"
    assert "cluster_membership" not in body["checks"]


@pytest.mark.asyncio
async def test_health_ready_returns_unavailable_when_configured_redis_is_down(monkeypatch):
    class _FailingRedis:
        async def ping(self):
            raise RuntimeError("redis unavailable at internal-cache:6379")

    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: _FailingRedis()),
    )

    resp = await health_ready()
    body_text = resp.body.decode()
    body = json.loads(body_text)

    assert resp.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"] == {"postgres": "up", "redis": "down"}
    assert "internal-cache:6379" not in body_text
