from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _sync_url(database_url: str, *, database: str) -> URL:
    return make_url(database_url).set(drivername="postgresql+psycopg", database=database)


def _alembic_env(database_url: str, *, database: str) -> dict[str, str]:
    url = make_url(database_url)
    port = str(url.port or 5432)
    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_HOST": url.host or "localhost",
            "POSTGRES_PORT": port,
            "POSTGRES_PORT_HOST": port,
            "POSTGRES_USER": url.username or "postgres",
            "POSTGRES_PASSWORD": url.password or "postgres",
            "POSTGRES_DB": database,
            "UV_NO_SYNC": "1",
        }
    )
    return env


def _run_alembic(database_url: str, *, database: str, target: str) -> None:
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        check=True,
        env=_alembic_env(database_url, database=database),
    )


@pytest.mark.no_db
def test_soft_delete_migration_repairs_duplicate_global_trigger_names(postgres_url: str) -> None:
    database = f"joysafeter_migration_{uuid.uuid4().hex}"
    admin_engine = create_engine(_sync_url(postgres_url, database="postgres"), isolation_level="AUTOCOMMIT")
    app_engine = create_engine(_sync_url(postgres_url, database=database))

    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{database}"'))

    try:
        _run_alembic(postgres_url, database=database, target="20260728_000002")

        agent_id = uuid.uuid4()
        keep_trigger_id = uuid.uuid4()
        delete_trigger_id = uuid.uuid4()
        with app_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO joysafeter_agents (id, name, engine_kind, permission_mode, version)
                    VALUES (:agent_id, 'migration-trigger-agent', 'codex', 'default', 1)
                    """
                ),
                {"agent_id": agent_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO joysafeter_triggers (
                        id, name, type, agent_id, prompt_template, enabled, config,
                        next_run_at, last_success_at, last_attempt_at, created_at, updated_at
                    )
                    VALUES (
                        :trigger_id, 'dup-global', 'cron', :agent_id, 'run me', true,
                        '{"next_run_at":"2026-07-29T10:00:00Z"}'::jsonb,
                        '2026-07-29T10:00:00Z', '2026-07-29T09:00:00Z', '2026-07-29T09:00:00Z',
                        '2026-07-01T00:00:00Z', '2026-07-29T09:00:00Z'
                    )
                    """
                ),
                {"trigger_id": keep_trigger_id, "agent_id": agent_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO joysafeter_triggers (
                        id, name, type, agent_id, prompt_template, enabled, config,
                        next_run_at, last_success_at, last_attempt_at, locked_by, locked_at,
                        pending_slot_at, slot_attempts, created_at, updated_at
                    )
                    VALUES (
                        :trigger_id, 'dup-global', 'cron', :agent_id, 'run me too', true,
                        '{"next_run_at":"2026-07-29T09:00:00Z","locked_by":"worker-old"}'::jsonb,
                        '2026-07-29T09:00:00Z', '2026-07-28T09:00:00Z', '2026-07-28T09:00:00Z',
                        'worker-old', '2026-07-29T08:58:00Z', '2026-07-29T09:00:00Z', 3,
                        '2026-07-02T00:00:00Z', '2026-07-28T09:00:00Z'
                    )
                    """
                ),
                {"trigger_id": delete_trigger_id, "agent_id": agent_id},
            )

        _run_alembic(postgres_url, database=database, target="head")

        with app_engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                    SELECT id::text AS id, enabled, next_run_at, locked_by, locked_at,
                           pending_slot_at, slot_attempts, deleted_at, disabled_reason, config
                      FROM joysafeter_triggers
                     WHERE name = 'dup-global'
                  ORDER BY deleted_at NULLS FIRST, id
                    """
                    )
                )
                .mappings()
                .all()
            )

            assert len(rows) == 2
            live_rows = [row for row in rows if row["deleted_at"] is None]
            deleted_rows = [row for row in rows if row["deleted_at"] is not None]
            assert [row["id"] for row in live_rows] == [str(keep_trigger_id)]
            assert [row["id"] for row in deleted_rows] == [str(delete_trigger_id)]

            deleted = deleted_rows[0]
            assert deleted["enabled"] is False
            assert deleted["next_run_at"] is None
            assert deleted["locked_by"] is None
            assert deleted["locked_at"] is None
            assert deleted["pending_slot_at"] is None
            assert deleted["slot_attempts"] == 0
            assert deleted["disabled_reason"] == "soft-deleted by 20260729_000001: duplicate global trigger name"
            assert deleted["config"]["enabled"] is False
            assert deleted["config"]["deleted_reason"] == "duplicate_global_trigger_name"

            with pytest.raises(IntegrityError):
                with app_engine.begin() as duplicate_conn:
                    duplicate_conn.execute(
                        text(
                            """
                            INSERT INTO joysafeter_triggers (id, name, type, agent_id, prompt_template, enabled)
                            VALUES (:trigger_id, 'dup-global', 'webhook', :agent_id, 'blocked', true)
                            """
                        ),
                        {"trigger_id": uuid.uuid4(), "agent_id": agent_id},
                    )
    finally:
        app_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :database"),
                {"database": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin_engine.dispose()
