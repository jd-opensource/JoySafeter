from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC = Path(sys.executable).with_name("alembic")
PREVIOUS_REVISION = "20260824_000001"


@dataclass(frozen=True)
class MigrationDatabase:
    dsn: str
    env: dict[str, str]


@pytest.fixture(scope="module")
def postgres_server() -> Iterator[tuple[str, int]]:
    with PostgresContainer(
        "postgres:15-alpine",
        username="postgres",
        password="postgres",
        dbname="postgres",
    ) as postgres:
        host = postgres.get_container_host_ip()
        yield ("127.0.0.1" if host in ("", "localhost", "127.0.0.1") else host, int(postgres.get_exposed_port(5432)))


@pytest.fixture
def migration_database(postgres_server: tuple[str, int]) -> Iterator[MigrationDatabase]:
    host, port = postgres_server
    database_name = f"network_policy_{uuid4().hex}"
    admin_dsn = f"postgresql://postgres:postgres@{host}:{port}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_HOST": host,
            "POSTGRES_PORT": str(port),
            "POSTGRES_PORT_HOST": str(port),
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "POSTGRES_DB": database_name,
            "SECRET_KEY": "test-secret-key-for-local-and-ci-runs-only",
            "JOYSAFETER_VAULT_ENCRYPTION_KEY": "0" * 64,
        }
    )
    subprocess.run(
        [ALEMBIC, "upgrade", PREVIOUS_REVISION],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield MigrationDatabase(
            dsn=f"postgresql://postgres:postgres@{host}:{port}/{database_name}",
            env=env,
        )
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def run_alembic(database: MigrationDatabase, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, *args],
        cwd=BACKEND_ROOT,
        env=database.env,
        capture_output=True,
        text=True,
    )


def test_network_policy_generation_migration_maps_only_ready_rows_to_applied(
    migration_database: MigrationDatabase,
) -> None:
    rows = [
        (uuid4(), "ready", "ready-hash", 4, None),
        (uuid4(), "pending", "pending-hash", 5, None),
        (uuid4(), "nacked", "nacked-hash", 6, None),
        (uuid4(), "disabled", None, 0, None),
        (uuid4(), "nacked", "destroyed-hash", 7, "2026-08-26 00:00:00+00"),
    ]
    with psycopg.connect(migration_database.dsn) as connection:
        connection.cursor().executemany(
            """
            INSERT INTO joysafeter_sandboxes
                (id, external_id, provider, status, config, image, networking_status,
                 networking_policy_hash, networking_policy_version, destroyed_at)
            VALUES (%s, %s, 'docker', 'idle', '{}'::jsonb, 'sandbox:test', %s, %s, %s, %s)
            """,
            [
                (sandbox_id, f"sandbox-{sandbox_id}", status, policy_hash, version, destroyed_at)
                for sandbox_id, status, policy_hash, version, destroyed_at in rows
            ],
        )

    result = run_alembic(migration_database, "upgrade", "20260824_000002")
    assert result.returncode == 0, result.stderr

    with psycopg.connect(migration_database.dsn) as connection:
        states = connection.execute(
            """
            SELECT id, networking_status, networking_policy_hash, networking_policy_version,
                   networking_applied_hash, networking_applied_version
            FROM joysafeter_sandboxes
            ORDER BY networking_policy_version
            """
        ).fetchall()

    by_id = {row[0]: row[1:] for row in states}
    assert by_id[rows[0][0]] == ("ready", "ready-hash", 4, "ready-hash", 4)
    assert by_id[rows[1][0]] == ("pending", "pending-hash", 5, None, None)
    assert by_id[rows[2][0]] == ("nacked", "nacked-hash", 6, None, None)
    assert by_id[rows[3][0]] == ("disabled", None, 0, None, None)
    assert by_id[rows[4][0]] == ("nacked", "destroyed-hash", 7, None, None)

    result = run_alembic(migration_database, "downgrade", PREVIOUS_REVISION)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(migration_database.dsn) as connection:
        desired = connection.execute(
            """
            SELECT id, networking_policy_hash, networking_policy_version
            FROM joysafeter_sandboxes
            ORDER BY networking_policy_version
            """
        ).fetchall()
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'joysafeter_sandboxes'
                """
            ).fetchall()
        }

    assert {row[0]: row[1:] for row in desired} == {
        sandbox_id: (policy_hash, version)
        for sandbox_id, _, policy_hash, version, _ in rows
    }
    assert "networking_applied_hash" not in columns
    assert "networking_applied_version" not in columns
