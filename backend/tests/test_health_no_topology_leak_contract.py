"""The unauthenticated readiness endpoint must not leak internal fleet state.

`GET /api/v1/health` (and `/ready`) is reachable without authentication so load
balancers can probe it. It must expose only up/down/degraded booleans — never
the orchestrator fleet topology (live/stale counts, heartbeat/expiry timestamps)
or raw database exception text, which would let an untrusted tenant fingerprint
the fleet and time attacks on low-capacity windows.
"""

import json

import pytest

from app.joysafeter_api.api.v1 import health as health_module
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

    async def fake_cluster(db):
        return {
            "status": "ok",
            "live_orchestrators": 3,
            "stale_orchestrators": 1,
            "newest_heartbeat_at": "2026-07-17T00:00:00",
            "newest_expires_at": "2026-07-17T00:05:00",
        }

    monkeypatch.setattr(health_module, "collect_cluster_membership_health", fake_cluster)

    resp = await health_ready()
    body_text = resp.body.decode()

    for leaked in ("live_orchestrators", "stale_orchestrators", "newest_heartbeat_at", "newest_expires_at"):
        assert leaked not in body_text, f"unauthenticated /ready must not expose {leaked}"

    body = json.loads(body_text)
    # It must still convey overall + per-dependency readiness.
    assert body["status"] in ("ok", "degraded")
    assert body["checks"]["postgres"] == "up"
    assert body["checks"]["cluster_membership"] in ("ok", "degraded", "unknown")


@pytest.mark.asyncio
async def test_health_ready_does_not_leak_db_error_text(monkeypatch):
    _patch_probes(monkeypatch)

    async def boom(db):
        raise RuntimeError('relation "joysafeter_cluster_members" does not exist on host db-primary:5432')

    monkeypatch.setattr(health_module, "collect_cluster_membership_health", boom)

    resp = await health_ready()
    body_text = resp.body.decode()

    assert "does not exist" not in body_text, "raw DB exception text must not reach an anonymous caller"
    assert "db-primary:5432" not in body_text
    body = json.loads(body_text)
    # Postgres SELECT 1 still succeeded, so the probe degrades cluster status but stays 200.
    assert body["checks"]["cluster_membership"] in ("degraded", "unknown")
