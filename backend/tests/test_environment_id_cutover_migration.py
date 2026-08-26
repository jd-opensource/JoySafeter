from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.no_db

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20260825_000004_type_environment_links.py"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).with_name("alembic")
VAULT_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


@dataclass(frozen=True)
class MigrationDatabase:
    dsn: str
    env: dict[str, str]


@pytest.fixture(scope="module")
def environment_link_postgres_server() -> Iterator[tuple[str, int, str, str]]:
    external_url = os.environ.get("JOYSAFETER_TEST_DATABASE_URL")
    if external_url:
        url = make_url(external_url)
        yield (
            url.host or "127.0.0.1",
            int(url.port or 5432),
            url.username or "postgres",
            url.password or "postgres",
        )
        return

    with PostgresContainer(
        "postgres:15-alpine",
        username="postgres",
        password="postgres",
        dbname="postgres",
    ) as postgres:
        host = postgres.get_container_host_ip()
        yield (
            "127.0.0.1" if host in ("", "localhost", "127.0.0.1") else host,
            int(postgres.get_exposed_port(5432)),
            "postgres",
            "postgres",
        )


@pytest.fixture
def environment_link_migration_database(
    environment_link_postgres_server: tuple[str, int, str, str],
) -> Iterator[MigrationDatabase]:
    host, port, username, password = environment_link_postgres_server
    database_name = f"environment_ids_{uuid4().hex}"
    admin_dsn = f"postgresql://{username}:{password}@{host}:{port}/postgres"

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    env = os.environ.copy()
    env.update(
        {
            "POSTGRES_HOST": host,
            "POSTGRES_PORT": str(port),
            "POSTGRES_PORT_HOST": str(port),
            "POSTGRES_USER": username,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": database_name,
            "SECRET_KEY": "test-secret-key-for-local-and-ci-runs-only",
            "JOYSAFETER_VAULT_ENCRYPTION_KEY": VAULT_KEY,
        }
    )
    result = _upgrade_to(env, "20260825_000003")
    assert result.returncode == 0, result.stderr

    try:
        yield MigrationDatabase(
            dsn=f"postgresql://{username}:{password}@{host}:{port}/{database_name}",
            env=env,
        )
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def _upgrade_to(env: dict[str, str], revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _insert_environment(connection: psycopg.Connection, *, name: str, project_id: UUID | None = None) -> UUID:
    environment_id = uuid4()
    connection.execute(
        """
        INSERT INTO joysafeter_environments (id, project_id, name, description, image_version)
        VALUES (%s, %s, %s, '', 0)
        """,
        (environment_id, project_id, name),
    )
    return environment_id


def _insert_agent(
    connection: psycopg.Connection,
    *,
    environment_ref: str | None,
    project_id: UUID | None = None,
) -> UUID:
    agent_id = uuid4()
    connection.execute(
        """
        INSERT INTO joysafeter_agents
            (id, project_id, name, engine_kind, permission_mode, version, environment_ref)
        VALUES (%s, %s, %s, 'claude', 'bypassPermissions', 1, %s)
        """,
        (agent_id, project_id, f"agent-{agent_id}", environment_ref),
    )
    return agent_id


def _insert_project(connection: psycopg.Connection, *, suffix: str) -> UUID:
    user_id = uuid4()
    organization_id = uuid4()
    project_id = uuid4()
    connection.execute(
        """
        INSERT INTO joysafeter_users
            (id, name, email, email_verified, is_active, is_super_user, failed_login_attempts)
        VALUES (%s, %s, %s, true, true, false, 0)
        """,
        (user_id, f"User {suffix}", f"{suffix}@example.com"),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_organizations
            (id, name, slug, storage_used_bytes, departed_member_usage)
        VALUES (%s, %s, %s, 0, 0)
        """,
        (organization_id, f"Organization {suffix}", f"organization-{suffix}"),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_organization_projects
            (id, org_id, name, slug, is_default, created_by_user_id)
        VALUES (%s, %s, %s, %s, true, %s)
        """,
        (project_id, organization_id, f"Project {suffix}", f"project-{suffix}", user_id),
    )
    return project_id


def _migration_module():
    spec = importlib.util.spec_from_file_location("type_environment_links", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_link_migration_targets_all_runtime_owners():
    migration = _migration_module()

    assert migration.ENVIRONMENT_LINK_TABLES == (
        "joysafeter_agents",
        "joysafeter_sessions",
        "joysafeter_triggers",
    )


def test_environment_reference_resolution_is_project_scoped_and_canonical():
    migration = _migration_module()
    sql = migration.resolve_reference_sql("source.environment_ref", "source.project_id")

    assert "environment.project_id IS NOT DISTINCT FROM source.project_id" in sql
    assert "environment.name = NULLIF(btrim(source.environment_ref), '')" in sql
    assert "'env_' || environment.id::text = NULLIF(btrim(source.environment_ref), '')" in sql
    assert "environment.deleted_at IS NULL" in sql


def test_environment_link_migration_fails_closed_on_unresolved_references():
    migration = _migration_module()

    with pytest.raises(RuntimeError, match="joysafeter_sessions: 2 unresolved environment references"):
        migration.raise_for_resolution_failures([("joysafeter_sessions", 2)])


def test_environment_link_migration_removes_legacy_snapshot_key():
    migration = _migration_module()
    sql = migration.snapshot_rewrite_sql(
        table="joysafeter_sessions",
        json_column="agent_snapshot",
    )

    assert "- 'environment_ref'" in sql
    assert "jsonb_build_object('environment_id'" in sql
    assert "'env_' || environment_id::text" in sql


def test_postgres_migration_materializes_environment_ids_and_rewrites_snapshots(
    environment_link_migration_database: MigrationDatabase,
):
    database = environment_link_migration_database
    with psycopg.connect(database.dsn) as connection:
        named_environment_id = _insert_environment(connection, name="development")
        prefixed_environment_id = _insert_environment(connection, name="production")
        snapshot_environment_id = _insert_environment(connection, name="snapshot")
        explicit_environment_id = _insert_environment(connection, name="explicit")

        named_agent_id = _insert_agent(connection, environment_ref=" development ")
        prefixed_agent_id = _insert_agent(connection, environment_ref=f"env_{prefixed_environment_id}")

        inherited_trigger_id = uuid4()
        connection.execute(
            """
            INSERT INTO joysafeter_triggers
                (id, name, type, agent_id, prompt_template, environment_ref)
            VALUES (%s, 'inherited-trigger', 'webhook', %s, 'run', NULL)
            """,
            (inherited_trigger_id, prefixed_agent_id),
        )
        explicit_trigger_id = uuid4()
        connection.execute(
            """
            INSERT INTO joysafeter_triggers
                (id, name, type, agent_id, prompt_template, environment_ref)
            VALUES (%s, 'explicit-trigger', 'webhook', %s, 'run', 'development')
            """,
            (explicit_trigger_id, prefixed_agent_id),
        )

        inherited_session_id = uuid4()
        connection.execute(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES (%s, %s, 'idle')",
            (inherited_session_id, prefixed_agent_id),
        )
        snapshot_session_id = uuid4()
        connection.execute(
            """
            INSERT INTO joysafeter_sessions (id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, 'idle', %s)
            """,
            (
                snapshot_session_id,
                named_agent_id,
                Jsonb({"environment_ref": "snapshot", "name": "snapshot-session"}),
            ),
        )
        explicit_session_id = uuid4()
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, agent_id, status, environment_ref, agent_snapshot)
            VALUES (%s, %s, 'idle', %s, %s)
            """,
            (
                explicit_session_id,
                named_agent_id,
                f"env_{explicit_environment_id}",
                Jsonb({"environment_ref": "snapshot", "name": "explicit-session"}),
            ),
        )
        agent_version_id = uuid4()
        connection.execute(
            """
            INSERT INTO joysafeter_agent_versions (id, agent_id, version, snapshot)
            VALUES (%s, %s, 1, %s)
            """,
            (
                agent_version_id,
                named_agent_id,
                Jsonb({"environment_ref": "development", "name": "version-snapshot"}),
            ),
        )
        connection.commit()

    result = _upgrade_to(database.env, "head")
    assert result.returncode == 0, result.stderr

    with psycopg.connect(database.dsn) as connection:
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_agents WHERE id = %s",
                (named_agent_id,),
            ).fetchone()[0]
            == named_environment_id
        )
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_agents WHERE id = %s",
                (prefixed_agent_id,),
            ).fetchone()[0]
            == prefixed_environment_id
        )
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_triggers WHERE id = %s",
                (inherited_trigger_id,),
            ).fetchone()[0]
            == prefixed_environment_id
        )
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_triggers WHERE id = %s",
                (explicit_trigger_id,),
            ).fetchone()[0]
            == named_environment_id
        )
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_sessions WHERE id = %s",
                (inherited_session_id,),
            ).fetchone()[0]
            == prefixed_environment_id
        )
        assert (
            connection.execute(
                "SELECT environment_id FROM joysafeter_sessions WHERE id = %s",
                (snapshot_session_id,),
            ).fetchone()[0]
            == snapshot_environment_id
        )
        explicit_environment, explicit_snapshot = connection.execute(
            "SELECT environment_id, agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (explicit_session_id,),
        ).fetchone()
        assert explicit_environment == explicit_environment_id
        assert explicit_snapshot == {
            "environment_id": f"env_{explicit_environment_id}",
            "name": "explicit-session",
        }
        assert connection.execute(
            "SELECT snapshot FROM joysafeter_agent_versions WHERE id = %s",
            (agent_version_id,),
        ).fetchone()[0] == {
            "environment_id": f"env_{named_environment_id}",
            "name": "version-snapshot",
        }

        columns = {
            (table_name, column_name, data_type)
            for table_name, column_name, data_type in connection.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                  AND column_name IN ('environment_id', 'environment_ref')
                """,
                (list(_migration_module().ENVIRONMENT_LINK_TABLES),),
            ).fetchall()
        }
        assert columns == {(table, "environment_id", "uuid") for table in _migration_module().ENVIRONMENT_LINK_TABLES}
        foreign_keys = {
            row[0] for row in connection.execute("SELECT conname FROM pg_constraint WHERE contype = 'f'").fetchall()
        }
        assert set(_migration_module().ENVIRONMENT_FOREIGN_KEYS.values()) <= foreign_keys


@pytest.mark.parametrize("invalid_kind", ["missing", "bare_uuid", "cross_project", "deleted"])
def test_postgres_migration_rejects_noncanonical_or_out_of_scope_references(
    environment_link_migration_database: MigrationDatabase,
    invalid_kind: str,
):
    database = environment_link_migration_database
    with psycopg.connect(database.dsn) as connection:
        project_id = None
        if invalid_kind == "cross_project":
            project_id = _insert_project(connection, suffix="source")
            environment_project_id = _insert_project(connection, suffix="environment")
        else:
            environment_project_id = None

        environment_id = _insert_environment(
            connection,
            name="target-environment",
            project_id=environment_project_id,
        )
        if invalid_kind == "missing":
            reference = "does-not-exist"
        elif invalid_kind == "bare_uuid":
            reference = str(environment_id)
        else:
            reference = f"env_{environment_id}"
        if invalid_kind == "deleted":
            connection.execute(
                "UPDATE joysafeter_environments SET deleted_at = now() WHERE id = %s",
                (environment_id,),
            )
        _insert_agent(connection, environment_ref=reference, project_id=project_id)
        connection.commit()

    result = _upgrade_to(database.env, "head")

    assert result.returncode != 0
    assert "joysafeter_agents: 1 unresolved environment references" in result.stderr
    with psycopg.connect(database.dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260825_000003"
        assert (
            connection.execute(
                """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_name = 'joysafeter_agents' AND column_name = 'environment_id'
            """
            ).fetchone()[0]
            == 0
        )
