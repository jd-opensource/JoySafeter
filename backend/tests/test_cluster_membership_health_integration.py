from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.joysafeter_api.api.v1.health import collect_cluster_membership_health


@pytest.mark.asyncio
async def test_cluster_membership_health_reads_real_pg_registry(db_session):
    now = datetime.now(UTC)
    live_id = "health-test-live-orchestrator"
    stale_id = "health-test-stale-orchestrator"

    await db_session.execute(
        text(
            """
            DELETE FROM joysafeter_cluster_members
            WHERE instance_id IN (:live_id, :stale_id)
            """
        ),
        {"live_id": live_id, "stale_id": stale_id},
    )
    try:
        await db_session.execute(
            text(
                """
                INSERT INTO joysafeter_cluster_members (
                    instance_id,
                    role,
                    started_at,
                    heartbeat_at,
                    expires_at,
                    metadata
                )
                VALUES
                    (
                        :live_id,
                        'orchestrator',
                        :now,
                        :now,
                        :live_expires_at,
                        '{"hostname": "test-host-live", "version": "test-version"}'
                    ),
                    (
                        :stale_id,
                        'orchestrator',
                        :now,
                        :stale_heartbeat_at,
                        :stale_expires_at,
                        '{"hostname": "test-host-stale", "version": "test-version"}'
                    )
                """
            ),
            {
                "live_id": live_id,
                "stale_id": stale_id,
                "now": now,
                "live_expires_at": now + timedelta(minutes=1),
                "stale_heartbeat_at": now - timedelta(minutes=10),
                "stale_expires_at": now - timedelta(minutes=9),
            },
        )

        health = await collect_cluster_membership_health(db_session)

        assert health["status"] == "ok"
        assert health["live_orchestrators"] == 1
        assert health["stale_orchestrators"] == 1
        assert health["newest_heartbeat_at"] is not None
        assert health["newest_expires_at"] is not None
    finally:
        await db_session.execute(
            text(
                """
                DELETE FROM joysafeter_cluster_members
                WHERE instance_id IN (:live_id, :stale_id)
                """
            ),
            {"live_id": live_id, "stale_id": stale_id},
        )
        await db_session.commit()
