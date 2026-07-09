from datetime import datetime, timezone

import pytest

from app.joysafeter_api.api.v1.health import collect_cluster_membership_health


pytestmark = pytest.mark.no_db


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return _FakeResult(self.row)


@pytest.mark.asyncio
async def test_cluster_membership_health_reports_live_orchestrators():
    heartbeat_at = datetime(2026, 7, 9, 6, 30, tzinfo=timezone.utc)
    expires_at = datetime(2026, 7, 9, 6, 31, tzinfo=timezone.utc)
    db = _FakeDb(
        {
            "live_orchestrators": 2,
            "stale_orchestrators": 1,
            "newest_heartbeat_at": heartbeat_at,
            "newest_expires_at": expires_at,
        }
    )

    health = await collect_cluster_membership_health(db)

    assert health == {
        "status": "ok",
        "live_orchestrators": 2,
        "stale_orchestrators": 1,
        "newest_heartbeat_at": heartbeat_at.isoformat(),
        "newest_expires_at": expires_at.isoformat(),
    }
    assert "joysafeter_cluster_members" in db.statements[0]
    assert "expires_at > NOW()" in db.statements[0]


@pytest.mark.asyncio
async def test_cluster_membership_health_degrades_when_no_orchestrator_is_live():
    db = _FakeDb(
        {
            "live_orchestrators": 0,
            "stale_orchestrators": 3,
            "newest_heartbeat_at": None,
            "newest_expires_at": None,
        }
    )

    health = await collect_cluster_membership_health(db)

    assert health == {
        "status": "degraded",
        "live_orchestrators": 0,
        "stale_orchestrators": 3,
        "newest_heartbeat_at": None,
        "newest_expires_at": None,
        "reason": "no_live_orchestrator",
    }
