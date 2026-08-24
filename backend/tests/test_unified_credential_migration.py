from __future__ import annotations

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
from testcontainers.postgres import PostgresContainer

from app.joysafeter_shared.security.credential_cipher import CredentialCipher

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC = Path(sys.executable).with_name("alembic")
PRE_UNIFIED_REVISION = "20260803_000001"
PROJECT_ID = "proj-migration"
ORG_ID = "org-migration"
VAULT_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _cipher(key: str = VAULT_KEY) -> CredentialCipher:
    return CredentialCipher(key)


def _legacy_ciphertext(plaintext: str, *, key: str = VAULT_KEY) -> str:
    current = _cipher(key).encrypt(plaintext)
    return "enc:" + current[len("enc:v1:") :]


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
    database_name = f"migration_{uuid4().hex}"
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
            "JOYSAFETER_VAULT_ENCRYPTION_KEY": VAULT_KEY,
        }
    )
    subprocess.run(
        [ALEMBIC, "upgrade", PRE_UNIFIED_REVISION],
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


def _upgrade_head(database: MigrationDatabase) -> subprocess.CompletedProcess[str]:
    return _upgrade_to(database, "head")


def _upgrade_to(database: MigrationDatabase, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=database.env,
        capture_output=True,
        text=True,
    )


def _downgrade_to(database: MigrationDatabase, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, "downgrade", revision],
        cwd=BACKEND_ROOT,
        env=database.env,
        capture_output=True,
        text=True,
    )


def _connect(database: MigrationDatabase) -> psycopg.Connection:
    return psycopg.connect(database.dsn)


def test_credential_access_audit_migration_is_append_only_and_runtime_idempotent(
    migration_database: MigrationDatabase,
) -> None:
    previous_revision = "20260821_000004"
    result = _upgrade_to(migration_database, previous_revision)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        assert connection.execute("SELECT to_regclass('joysafeter_credential_access_audits')").fetchone()[0] is None

    result = _upgrade_to(migration_database, "20260822_000001")
    assert result.returncode == 0, result.stderr

    credential_id = uuid4()
    audit_id = uuid4()
    session_id = uuid4()
    with _connect(migration_database) as connection:
        connection.autocommit = True
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_credential_access_audits'
                """
            ).fetchall()
        }
        assert "updated_at" not in columns
        assert {
            "credential_id",
            "field_names",
            "result",
            "created_at",
            "user_id",
            "org_id",
            "role",
            "ip_address",
            "user_agent",
        } <= columns
        assert "credential_public_id" not in columns

        credential_foreign_keys = connection.execute(
            """
            SELECT constraint_name
            FROM information_schema.constraint_column_usage
            WHERE table_name = 'joysafeter_credential_access_audits'
              AND column_name = 'credential_id'
            """
        ).fetchall()
        assert credential_foreign_keys == []

        index_definition = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE indexname = 'uq_credential_access_audits_runtime_success'
            """
        ).fetchone()[0]
        assert "NULLS NOT DISTINCT" in index_definition
        assert "result" in index_definition
        assert "'success'" in index_definition
        assert "session_id IS NOT NULL" in index_definition
        assert "generation IS NOT NULL" in index_definition

        principal_index_definition = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE indexname = 'ix_credential_access_audits_principal_created'
            """
        ).fetchone()[0]
        assert "principal_type" in principal_index_definition
        assert "principal_id" in principal_index_definition
        assert "created_at" in principal_index_definition

        values = (
            audit_id,
            PROJECT_ID,
            credential_id,
            "service",
            "http_egress",
            "sandbox",
            None,
            "system",
            "runtime",
            session_id,
            1,
            Jsonb(["TOKEN"]),
            "success",
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credential_access_audits
                (id, project_id, credential_id, credential_kind, usage,
                 consumer_type, consumer_id, principal_type, principal_id,
                 session_id, generation, field_names, result)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                """
                INSERT INTO joysafeter_credential_access_audits
                    (id, project_id, credential_id, credential_kind, usage,
                     consumer_type, consumer_id, principal_type, principal_id,
                     session_id, generation, field_names, result)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (uuid4(), *values[1:]),
            )

        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                "UPDATE joysafeter_credential_access_audits SET result = 'failed' WHERE id = %s",
                (audit_id,),
            )

        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                "DELETE FROM joysafeter_credential_access_audits WHERE id = %s",
                (audit_id,),
            )

    result = _downgrade_to(migration_database, previous_revision)
    assert result.returncode == 0, result.stderr
    with _connect(migration_database) as connection:
        assert connection.execute("SELECT to_regclass('joysafeter_credential_access_audits')").fetchone()[0] is None
        function_exists = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'prevent_credential_access_audit_mutation')"
        ).fetchone()[0]
        assert function_exists is False


def _seed_project(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_organizations
            (id, name, slug, storage_used_bytes, departed_member_usage)
        VALUES (%s, 'Migration Org', 'migration-org', 0, 0)
        """,
        (ORG_ID,),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_organization_projects
            (id, org_id, name, slug, is_default)
        VALUES (%s, %s, 'Migration Project', 'migration-project', true)
        """,
        (PROJECT_ID, ORG_ID),
    )


def _seed_agent(
    connection: psycopg.Connection,
    *,
    agent_id: UUID,
    name: str,
    secret_ref: str | None = None,
    mcp_configs: object | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_agents
            (id, project_id, name, engine_kind, env, mcp_configs, skills, tools,
             agents, commands, permission_mode, metadata, version, secret_ref)
        VALUES
            (%s, %s, %s, 'codex', '{}'::jsonb, %s, '[]'::jsonb, '[]'::jsonb,
             '[]'::jsonb, '[]'::jsonb, 'default', '{}'::jsonb, 1, %s)
        """,
        (agent_id, PROJECT_ID, name, Jsonb(mcp_configs or []), secret_ref),
    )


def _seed_trigger(
    connection: psycopg.Connection,
    *,
    trigger_id: UUID,
    agent_id: UUID,
    secret_ref: str,
) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_triggers
            (id, project_id, name, type, agent_id, prompt_template, secret_ref, secret_key)
        VALUES (%s, %s, %s, 'webhook', %s, 'Run', %s, 'authorization')
        """,
        (trigger_id, PROJECT_ID, f"trigger-{trigger_id}", agent_id, secret_ref),
    )


def _seed_vault(
    connection: psycopg.Connection,
    *,
    vault_id: UUID,
    name: str,
    metadata: dict[str, str] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_vaults (id, project_id, name, description, metadata)
        VALUES (%s, %s, %s, '', %s)
        """,
        (vault_id, PROJECT_ID, name, Jsonb(metadata or {})),
    )


def _seed_vault_credential(
    connection: psycopg.Connection,
    *,
    credential_id: UUID,
    vault_id: UUID,
    name: str,
    url: str,
    token: str,
    created_at: str = "2026-08-14T10:00:00Z",
) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_vault_credentials
            (id, vault_id, name, credential_type, mcp_server_url, token_value,
             created_at, updated_at)
        VALUES (%s, %s, %s, 'bearer', %s, %s, %s, %s)
        """,
        (credential_id, vault_id, name, url, token, created_at, created_at),
    )


def test_migration_renames_and_canonicalizes_mcp_configs(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    mcp_configs = [{"type": "url", "name": "github", "url": "https://mcp.example.test"}]
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="mcp-agent", mcp_configs=mcp_configs)
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_agents'
                """
            ).fetchall()
        }
        stored_value = connection.execute(
            "SELECT mcp_servers FROM joysafeter_agents WHERE id = %s",
            (agent_id,),
        ).fetchone()[0]

    assert "mcp_servers" in columns
    assert "mcp_configs" not in columns
    assert stored_value == [
        {
            "type": "streamable_http",
            "name": "github",
            "url": "https://mcp.example.test",
            "auth_requirement": "optional",
        }
    ]


def test_migration_adds_sandbox_runtime_config_freshness_columns(
    migration_database: MigrationDatabase,
) -> None:
    result = _upgrade_to(migration_database, "20260821_000002")
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        columns_before_upgrade = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_sandboxes'
                  AND column_name IN (
                      'runtime_config_status',
                      'runtime_config_last_reason',
                      'runtime_config_required_at'
                  )
                """
            ).fetchall()
        }

    assert columns_before_upgrade == set()

    result = _upgrade_to(migration_database, "20260821_000003")
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        columns = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                """
                SELECT column_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_sandboxes'
                  AND column_name IN (
                      'runtime_config_status',
                      'runtime_config_last_reason',
                      'runtime_config_required_at'
                  )
                """
            ).fetchall()
        }
        constraints = [
            row[0]
            for row in connection.execute(
                """
                SELECT pg_get_constraintdef(check_constraint.oid)
                FROM pg_constraint AS check_constraint
                JOIN pg_class AS relation ON relation.oid = check_constraint.conrelid
                WHERE relation.relname = 'joysafeter_sandboxes'
                  AND check_constraint.contype = 'c'
                """
            ).fetchall()
        ]

    assert columns.keys() == {
        "runtime_config_status",
        "runtime_config_last_reason",
        "runtime_config_required_at",
    }
    assert columns["runtime_config_status"] == ("NO", "'ready'::text")
    assert columns["runtime_config_last_reason"] == ("YES", None)
    assert columns["runtime_config_required_at"] == ("YES", None)
    assert any(
        all(value in definition for value in ("runtime_config_status", "ready", "restart_required"))
        for definition in constraints
    )

    result = _downgrade_to(migration_database, "20260821_000002")
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        columns_after_downgrade = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_sandboxes'
                  AND column_name IN (
                      'runtime_config_status',
                      'runtime_config_last_reason',
                      'runtime_config_required_at'
                  )
                """
            ).fetchall()
        }
        constraints_after_downgrade = {
            row[0]
            for row in connection.execute(
                """
                SELECT pg_get_constraintdef(pg_constraint.oid)
                FROM pg_constraint
                JOIN pg_class AS relation ON relation.oid = pg_constraint.conrelid
                WHERE relation.relname = 'joysafeter_sandboxes'
                  AND pg_get_constraintdef(pg_constraint.oid) LIKE '%runtime_config_status%'
                """
            ).fetchall()
        }

    assert columns_after_downgrade == set()
    assert constraints_after_downgrade == set()


def test_migration_adds_runtime_config_generations_with_conservative_backfill(
    migration_database: MigrationDatabase,
) -> None:
    result = _upgrade_to(migration_database, "20260821_000003")
    assert result.returncode == 0, result.stderr

    agent_id = uuid4()
    idle_session_id = uuid4()
    running_session_id = uuid4()
    rescheduling_session_id = uuid4()
    terminated_session_id = uuid4()
    archived_session_id = uuid4()
    raw_ready_sandbox_id = uuid4()
    raw_stale_sandbox_id = uuid4()
    destroyed_sandbox_id = uuid4()
    pool_sandbox_id = uuid4()
    required_at = "2026-08-20 12:34:56+00"

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'runtime-generation-agent', 'codex', '{}'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.cursor().executemany(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, archived_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (idle_session_id, PROJECT_ID, agent_id, "idle", None),
                (running_session_id, PROJECT_ID, agent_id, "running", None),
                (rescheduling_session_id, PROJECT_ID, agent_id, "rescheduling", None),
                (terminated_session_id, PROJECT_ID, agent_id, "terminated", None),
                (archived_session_id, PROJECT_ID, agent_id, "idle", "2026-08-20 10:00:00+00"),
            ],
        )
        connection.cursor().executemany(
            """
            INSERT INTO joysafeter_sandboxes
                (id, project_id, external_id, provider, status, config,
                 chat_session_id, image, destroyed_at, runtime_config_status,
                 runtime_config_last_reason, runtime_config_required_at)
            VALUES (%s, %s, %s, 'docker', %s, '{}'::jsonb, %s,
                    'sandbox:latest', %s, %s, %s, %s)
            """,
            [
                (
                    raw_ready_sandbox_id,
                    PROJECT_ID,
                    "runtime-generation-ready",
                    "idle",
                    idle_session_id,
                    None,
                    "ready",
                    None,
                    None,
                ),
                (
                    raw_stale_sandbox_id,
                    PROJECT_ID,
                    "runtime-generation-stale",
                    "stopped",
                    running_session_id,
                    None,
                    "restart_required",
                    "credential.updated",
                    required_at,
                ),
                (
                    destroyed_sandbox_id,
                    PROJECT_ID,
                    "runtime-generation-destroyed",
                    "idle",
                    rescheduling_session_id,
                    "2026-08-20 11:00:00+00",
                    "ready",
                    None,
                    None,
                ),
                (
                    pool_sandbox_id,
                    PROJECT_ID,
                    "runtime-generation-pool",
                    "pooled",
                    None,
                    None,
                    "ready",
                    None,
                    None,
                ),
            ],
        )
        connection.commit()

        columns_before_upgrade = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE (table_name = 'joysafeter_sessions'
                       AND column_name IN (
                           'runtime_config_generation',
                           'runtime_config_generation_reason',
                           'runtime_config_generation_updated_at'
                       ))
                   OR (table_name = 'joysafeter_sandboxes'
                       AND column_name = 'runtime_config_applied_generation')
                """
            ).fetchall()
        }

    assert columns_before_upgrade == set()

    result = _upgrade_to(migration_database, "20260821_000004")
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        session_columns = {
            row[0]: (row[1], row[2], row[3])
            for row in connection.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_sessions'
                  AND column_name IN (
                      'runtime_config_generation',
                      'runtime_config_generation_reason',
                      'runtime_config_generation_updated_at'
                  )
                """
            ).fetchall()
        }
        sandbox_columns = {
            row[0]: (row[1], row[2], row[3])
            for row in connection.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'joysafeter_sandboxes'
                  AND column_name = 'runtime_config_applied_generation'
                """
            ).fetchall()
        }
        session_rows = {
            row[0]: row[1:]
            for row in connection.execute(
                """
                SELECT id, runtime_config_generation,
                       runtime_config_generation_reason,
                       runtime_config_generation_updated_at
                FROM joysafeter_sessions
                WHERE id = ANY(%s)
                """,
                (
                    [
                        idle_session_id,
                        running_session_id,
                        rescheduling_session_id,
                        terminated_session_id,
                        archived_session_id,
                    ],
                ),
            ).fetchall()
        }
        sandbox_rows = {
            row[0]: row[1:]
            for row in connection.execute(
                """
                SELECT id, chat_session_id, destroyed_at, runtime_config_status,
                       runtime_config_last_reason, runtime_config_required_at,
                       runtime_config_applied_generation
                FROM joysafeter_sandboxes
                WHERE id = ANY(%s)
                """,
                (
                    [
                        raw_ready_sandbox_id,
                        raw_stale_sandbox_id,
                        destroyed_sandbox_id,
                        pool_sandbox_id,
                    ],
                ),
            ).fetchall()
        }

    assert session_columns == {
        "runtime_config_generation": ("bigint", "NO", "0"),
        "runtime_config_generation_reason": ("text", "YES", None),
        "runtime_config_generation_updated_at": ("timestamp with time zone", "YES", None),
    }
    assert sandbox_columns == {
        "runtime_config_applied_generation": ("bigint", "NO", "0"),
    }

    for session_id in (idle_session_id, running_session_id, rescheduling_session_id):
        generation, reason, updated_at = session_rows[session_id]
        assert generation == 1
        assert reason == "migration.runtime_config_generation_backfill"
        assert updated_at is not None

    assert session_rows[terminated_session_id] == (0, None, None)
    assert session_rows[archived_session_id] == (0, None, None)

    ready_row = sandbox_rows[raw_ready_sandbox_id]
    assert ready_row[2:] == ("ready", None, None, 0)
    assert ready_row[-1] != session_rows[idle_session_id][0]

    stale_row = sandbox_rows[raw_stale_sandbox_id]
    assert stale_row[2] == "restart_required"
    assert stale_row[3] == "credential.updated"
    assert stale_row[4].isoformat() == "2026-08-20T12:34:56+00:00"
    assert stale_row[5] == 0

    destroyed_row = sandbox_rows[destroyed_sandbox_id]
    assert destroyed_row[1] is not None
    assert destroyed_row[2:] == ("ready", None, None, 0)

    pool_row = sandbox_rows[pool_sandbox_id]
    assert pool_row == (None, None, "ready", None, None, 0)

    result = _downgrade_to(migration_database, "20260821_000003")
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        columns_after_downgrade = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE (table_name = 'joysafeter_sessions'
                       AND column_name IN (
                           'runtime_config_generation',
                           'runtime_config_generation_reason',
                           'runtime_config_generation_updated_at'
                       ))
                   OR (table_name = 'joysafeter_sandboxes'
                       AND column_name = 'runtime_config_applied_generation')
                """
            ).fetchall()
        }

    assert columns_after_downgrade == set()


def test_migration_rejects_normalized_mcp_url_collisions_before_creating_tables(
    migration_database: MigrationDatabase,
) -> None:
    vault_id = uuid4()
    first_credential_id = uuid4()
    second_credential_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_vault(connection, vault_id=vault_id, name="collision-vault")
        _seed_vault_credential(
            connection,
            credential_id=first_credential_id,
            vault_id=vault_id,
            name="first",
            url="https://MCP.example.test/",
            token=_legacy_ciphertext("first"),
        )
        _seed_vault_credential(
            connection,
            credential_id=second_credential_id,
            vault_id=vault_id,
            name="second",
            url="https://mcp.example.test",
            token=_legacy_ciphertext("second"),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "normalized MCP server URL collisions" in output
    assert str(first_credential_id) in output
    assert str(second_credential_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute("SELECT to_regclass('joysafeter_credentials')").fetchone()[0]
    assert target_exists is None


def test_migration_rejects_cross_table_credential_id_collisions_before_creating_tables(
    migration_database: MigrationDatabase,
) -> None:
    vault_id = uuid4()
    shared_credential_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_vault(connection, vault_id=vault_id, name="id-collision-vault")
        _seed_vault_credential(
            connection,
            credential_id=shared_credential_id,
            vault_id=vault_id,
            name="id-collision-mcp",
            url="https://collision.example.test",
            token=_legacy_ciphertext("mcp"),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES (%s, %s, 'id-collision-secret', 'custom', 'custom', '{}'::jsonb, false)
            """,
            (shared_credential_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "share the same id" in output
    assert str(shared_credential_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute("SELECT to_regclass('joysafeter_credentials')").fetchone()[0]
    assert target_exists is None


def test_migration_renames_duplicate_mcp_names_without_data_loss(
    migration_database: MigrationDatabase,
) -> None:
    older_vault_id = uuid4()
    newer_vault_id = uuid4()
    older_credential_id = uuid4()
    newer_credential_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_vault(connection, vault_id=older_vault_id, name="older-vault")
        _seed_vault(connection, vault_id=newer_vault_id, name="newer-vault")
        _seed_vault_credential(
            connection,
            credential_id=older_credential_id,
            vault_id=older_vault_id,
            name="shared-name",
            url="https://older.example.test",
            token=_legacy_ciphertext("older"),
            created_at="2026-08-13T10:00:00Z",
        )
        _seed_vault_credential(
            connection,
            credential_id=newer_credential_id,
            vault_id=newer_vault_id,
            name="shared-name",
            url="https://newer.example.test",
            token=_legacy_ciphertext("newer"),
            created_at="2026-08-14T10:00:00Z",
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        rows = connection.execute(
            """
            SELECT id, name, data->>'token_value'
            FROM joysafeter_credentials
            WHERE kind = 'mcp'
            ORDER BY created_at, id
            """
        ).fetchall()

    assert [(row[0], row[1]) for row in rows] == [
        (older_credential_id, f"shared-name (migrated-dup {older_credential_id})"),
        (newer_credential_id, "shared-name"),
    ]
    assert all(row[2].startswith("enc:v1:") for row in rows)
    assert [_cipher().decrypt_stored(row[2]) for row in rows] == ["older", "newer"]


def test_migration_preserves_vault_metadata_and_prefixed_session_references(
    migration_database: MigrationDatabase,
) -> None:
    first_vault_id = uuid4()
    second_vault_id = uuid4()
    session_id = uuid4()
    agent_id = uuid4()
    metadata = {"owner": "platform", "purpose": "legacy-mcp"}
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="prefixed-vault-agent")
        _seed_vault(
            connection,
            vault_id=first_vault_id,
            name="metadata-vault",
            metadata=metadata,
        )
        _seed_vault(connection, vault_id=second_vault_id, name="second-vault")
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, vault_ids)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    [
                        f"vault_{first_vault_id}",
                        f"vlt_{second_vault_id}",
                        str(first_vault_id),
                    ]
                ),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        stored_metadata = connection.execute(
            "SELECT metadata FROM joysafeter_credential_groups WHERE id = %s",
            (first_vault_id,),
        ).fetchone()[0]
        group_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT credential_group_id
                FROM joysafeter_session_credential_groups
                WHERE session_id = %s
                """,
                (session_id,),
            ).fetchall()
        }

    assert stored_metadata == metadata
    assert group_ids == {first_vault_id, second_vault_id}


def test_migration_preserves_legacy_trigger_system_prompt(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    trigger_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="legacy-system-prompt-agent")
        connection.execute(
            """
            INSERT INTO joysafeter_triggers
                (id, project_id, name, type, agent_id, prompt_template, system_prompt)
            VALUES (%s, %s, 'legacy-system-prompt-trigger', 'webhook', %s, 'Run', %s)
            """,
            (
                trigger_id,
                PROJECT_ID,
                agent_id,
                "Preserve these historical system instructions.",
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        stored_prompt = connection.execute(
            "SELECT system_prompt FROM joysafeter_triggers WHERE id = %s",
            (trigger_id,),
        ).fetchone()[0]

    assert stored_prompt == "Preserve these historical system instructions."


def test_migration_rejects_soft_deleted_null_project_before_creating_tables(
    migration_database: MigrationDatabase,
) -> None:
    secret_id = uuid4()
    with _connect(migration_database) as connection:
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default, deleted_at)
            VALUES (%s, NULL, 'orphaned', 'custom', 'custom', '{}'::jsonb, false, now())
            """,
            (secret_id,),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "NULL project_id" in output
    assert str(secret_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute("SELECT to_regclass('joysafeter_credentials')").fetchone()[0]
    assert target_exists is None


def test_migration_rejects_all_unresolved_legacy_references(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    missing_group_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="unresolved-agent", secret_ref="missing-model")
        _seed_trigger(
            connection,
            trigger_id=uuid4(),
            agent_id=agent_id,
            secret_ref="missing-service",
        )
        connection.execute(
            """
            INSERT INTO joysafeter_environments
                (id, project_id, name, description, image_version, config)
            VALUES
                (%s, %s, 'unresolved-env', '', 1,
                 %s)
            """,
            (
                uuid4(),
                PROJECT_ID,
                Jsonb(
                    {
                        "secret_refs": ["missing-service"],
                        "egress_services": [{"credential_ref": "missing-service"}],
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, vault_ids, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s, %s)
            """,
            (
                uuid4(),
                PROJECT_ID,
                agent_id,
                Jsonb([str(missing_group_id)]),
                Jsonb({"secret_ref": "missing-model"}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    for reference_kind in (
        "agents.secret_ref",
        "triggers.secret_ref",
        "environments.config.secret_refs",
        "environments.config.egress_services[].credential_ref",
        "sessions.vault_ids",
        "sessions.agent_snapshot.secret_ref",
    ):
        assert reference_kind in output


def test_migration_rejects_malformed_reference_json_before_creating_tables(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    environment_id = uuid4()
    session_id = uuid4()
    malformed_secret_ref_session_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="malformed-json-agent")
        connection.execute(
            """
            INSERT INTO joysafeter_environments
                (id, project_id, name, description, image_version, config)
            VALUES (%s, %s, 'malformed-env', '', 1, %s)
            """,
            (environment_id, PROJECT_ID, Jsonb(["legacy-secret-name"])),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, vault_ids, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s, %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(str(uuid4())),
                Jsonb([{"secret_ref": "legacy-secret-name"}]),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                malformed_secret_ref_session_id,
                PROJECT_ID,
                agent_id,
                Jsonb({"secret_ref": {"name": "legacy-secret-name"}}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "malformed legacy credential reference JSON" in output
    assert str(environment_id) in output
    assert str(session_id) in output
    assert str(malformed_secret_ref_session_id) in output
    assert "agent_snapshot.secret_ref must be a string or null" in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute("SELECT to_regclass('joysafeter_credentials')").fetchone()[0]
    assert target_exists is None


@pytest.mark.parametrize("secret_ref", [None, "", "   "])
def test_migration_accepts_empty_snapshot_secret_ref(
    migration_database: MigrationDatabase,
    secret_ref: str | None,
) -> None:
    agent_id = uuid4()
    session_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="empty-snapshot-secret-agent")
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb({"secret_ref": secret_ref}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        snapshot = connection.execute(
            "SELECT agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()[0]

    assert "secret_ref" not in snapshot


def test_migration_rejects_secret_consumed_as_both_model_and_service(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    secret_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="shared-agent", secret_ref="shared-secret")
        _seed_trigger(
            connection,
            trigger_id=uuid4(),
            agent_id=agent_id,
            secret_ref="shared-secret",
        )
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES (%s, %s, 'shared-secret', 'custom', 'custom', '{}'::jsonb, false)
            """,
            (secret_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "both model and service" in output
    assert str(secret_id) in output


def test_migration_classifies_snapshot_only_secret_as_model(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    session_id = uuid4()
    secret_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="snapshot-only-agent")
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES (%s, %s, 'snapshot-only', 'custom', 'custom', '{}'::jsonb, false)
            """,
            (secret_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb({"secret_ref": "snapshot-only"}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        credential_kind = connection.execute(
            "SELECT kind FROM joysafeter_credentials WHERE id = %s",
            (secret_id,),
        ).fetchone()[0]
        snapshot = connection.execute(
            "SELECT agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()[0]

    assert credential_kind == "model"
    assert snapshot["model_credential_id"] == f"cred_{secret_id}"
    assert "secret_ref" not in snapshot


def test_migration_classifies_default_custom_secret_as_model(
    migration_database: MigrationDatabase,
) -> None:
    secret_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES (%s, %s, 'default-custom', 'custom', 'custom', '{}'::jsonb, true)
            """,
            (secret_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        row = connection.execute(
            """
            SELECT kind, provider, protocol, is_default
            FROM joysafeter_credentials
            WHERE id = %s
            """,
            (secret_id,),
        ).fetchone()

    assert row == ("model", "custom", "custom", True)


def test_migration_rejects_duplicate_default_custom_protocol_before_creating_tables(
    migration_database: MigrationDatabase,
) -> None:
    first_secret_id = uuid4()
    second_secret_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES
                (%s, %s, 'default-custom-one', 'custom', 'custom', '{}'::jsonb, true),
                (%s, %s, 'default-custom-two', 'custom', 'custom', '{}'::jsonb, true)
            """,
            (first_secret_id, PROJECT_ID, second_secret_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "multiple default model secrets" in output
    assert str(first_secret_id) in output
    assert str(second_secret_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute("SELECT to_regclass('joysafeter_credentials')").fetchone()[0]
    assert target_exists is None


def test_migration_keeps_latest_live_duplicate_name_canonical(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    older_secret_id = uuid4()
    newer_secret_id = uuid4()
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="duplicate-agent", secret_ref="duplicate")
        connection.execute("DROP INDEX uq_joysafeter_secrets_project_name")
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default, created_at, updated_at)
            VALUES
                (%s, %s, 'duplicate', 'custom', 'custom', '{}'::jsonb, false,
                 '2026-08-13T10:00:00Z', '2026-08-13T10:00:00Z'),
                (%s, %s, 'duplicate', 'custom', 'custom', '{}'::jsonb, false,
                 '2026-08-14T10:00:00Z', '2026-08-14T10:00:00Z')
            """,
            (older_secret_id, PROJECT_ID, newer_secret_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        canonical_id = connection.execute(
            """
            SELECT id
            FROM joysafeter_credentials
            WHERE project_id = %s AND kind = 'model' AND name = 'duplicate'
            """,
            (PROJECT_ID,),
        ).fetchone()[0]
        referenced_id = connection.execute(
            "SELECT model_credential_id FROM joysafeter_agents WHERE id = %s",
            (agent_id,),
        ).fetchone()[0]

    assert canonical_id == newer_secret_id
    assert referenced_id == newer_secret_id


def test_migration_uses_id_tiebreaker_for_duplicate_canonical_selection(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    lower_secret_id = UUID("00000000-0000-0000-0000-000000000001")
    higher_secret_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(connection, agent_id=agent_id, name="tied-agent", secret_ref="tied")
        connection.execute("DROP INDEX uq_joysafeter_secrets_project_name")
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default, created_at, updated_at)
            VALUES
                (%s, %s, 'tied', 'custom', 'custom', '{}'::jsonb, false,
                 '2026-08-14T10:00:00Z', '2026-08-14T10:00:00Z'),
                (%s, %s, 'tied', 'custom', 'custom', '{}'::jsonb, false,
                 '2026-08-14T10:00:00Z', '2026-08-14T10:00:00Z')
            """,
            (higher_secret_id, PROJECT_ID, lower_secret_id, PROJECT_ID),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        canonical_id = connection.execute(
            """
            SELECT id
            FROM joysafeter_credentials
            WHERE project_id = %s AND kind = 'model' AND name = 'tied'
            """,
            (PROJECT_ID,),
        ).fetchone()[0]
        referenced_id = connection.execute(
            "SELECT model_credential_id FROM joysafeter_agents WHERE id = %s",
            (agent_id,),
        ).fetchone()[0]

    assert canonical_id == higher_secret_id
    assert referenced_id == higher_secret_id


def test_migration_converts_legacy_skill_usage_ids(
    migration_database: MigrationDatabase,
) -> None:
    usage_id = uuid4()
    session_id = uuid4()
    agent_id = uuid4()
    with _connect(migration_database) as connection:
        connection.execute(
            """
            INSERT INTO joysafeter_skill_usage_log
                (id, skill_version, session_id, agent_id)
            VALUES (%s, '1.2.3', %s, %s)
            """,
            (usage_id, f"sess_{session_id}", str(agent_id)),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        row = connection.execute(
            """
            SELECT session_id, agent_id, skill_version
            FROM joysafeter_skill_usage_log
            WHERE id = %s
            """,
            (usage_id,),
        ).fetchone()

    assert row == (session_id, agent_id, "1.2.3")


def test_envelope_normalization_covers_all_persisted_credential_stores(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260814_000002").returncode == 0

    agent_id = uuid4()
    session_id = uuid4()
    task_id = uuid4()
    model_credential_id = uuid4()
    mcp_credential_id = uuid4()
    group_id = uuid4()
    repo_id = uuid4()
    cipher = _cipher()
    legacy_model = _legacy_ciphertext("legacy-model")
    current_model = cipher.encrypt("current-model")
    legacy_token = _legacy_ciphertext("legacy-token")
    current_refresh = cipher.encrypt("current-refresh")
    legacy_repo = _legacy_ciphertext("repo-token")
    legacy_identity = _legacy_ciphertext("identity-token")

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'normalization-agent', 'codex', '{}'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions (id, project_id, agent_id, status)
            VALUES (%s, %s, %s, 'idle')
            """,
            (session_id, PROJECT_ID, agent_id),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_tasks
                (id, project_id, agent_id, chat_session_id, status, prompt, output,
                 timeout_sec, retry_count, max_retries)
            VALUES (%s, %s, %s, %s, 'pending', 'normalize', '', 7200, 0, 2)
            """,
            (task_id, PROJECT_ID, agent_id, session_id),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credential_groups (id, project_id, name)
            VALUES (%s, %s, 'normalization-group')
            """,
            (group_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default)
            VALUES (%s, %s, 'model', 'normalization-model', %s, 'anthropic', 'anthropic', false)
            """,
            (
                model_credential_id,
                PROJECT_ID,
                Jsonb(
                    {
                        "PLAINTEXT": "plaintext-model",
                        "LEGACY": legacy_model,
                        "CURRENT": current_model,
                        "EMPTY": "",
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, credential_type, mcp_server_url,
                 normalized_mcp_server_url, oauth_config, group_id, is_default)
            VALUES
                (%s, %s, 'mcp', 'normalization-mcp', %s, 'oauth',
                 'https://mcp.example.test', 'https://mcp.example.test', %s, %s, false)
            """,
            (
                mcp_credential_id,
                PROJECT_ID,
                Jsonb({"token_value": legacy_token}),
                Jsonb(
                    {
                        "client_id": "public-client",
                        "client_secret": "plaintext-client-secret",
                        "refresh_token": current_refresh,
                        "expires_at": 123,
                    }
                ),
                group_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_session_repos
                (id, session_id, url, branch, mount_path, mount_name, encrypted_token)
            VALUES (%s, %s, 'https://github.example/repo.git', '', '', 'repo', %s)
            """,
            (repo_id, session_id, legacy_repo),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_task_identity_contexts
                (task_id, project_id, user_id, user_name, credential_kind,
                 credential_fingerprint, encrypted_credential, captured_at, expires_at)
            VALUES
                (%s, %s, 'user-1', 'user@example.com', 'identity_token',
                 NULL, %s, NOW(), NOW() + INTERVAL '5 minutes')
            """,
            (task_id, PROJECT_ID, legacy_identity),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        model_data = connection.execute(
            "SELECT data FROM joysafeter_credentials WHERE id = %s",
            (model_credential_id,),
        ).fetchone()[0]
        mcp_data, oauth_config = connection.execute(
            "SELECT data, oauth_config FROM joysafeter_credentials WHERE id = %s",
            (mcp_credential_id,),
        ).fetchone()
        repo_token = connection.execute(
            "SELECT encrypted_token FROM joysafeter_session_repos WHERE id = %s",
            (repo_id,),
        ).fetchone()[0]
        identity_token = connection.execute(
            "SELECT encrypted_credential FROM joysafeter_task_identity_contexts WHERE task_id = %s",
            (task_id,),
        ).fetchone()[0]

    assert model_data["EMPTY"] == ""
    assert cipher.decrypt_stored(model_data["PLAINTEXT"]) == "plaintext-model"
    assert cipher.decrypt_stored(model_data["LEGACY"]) == "legacy-model"
    assert model_data["CURRENT"] == current_model
    assert cipher.decrypt_stored(mcp_data["token_value"]) == "legacy-token"
    assert oauth_config["client_id"] == "public-client"
    assert oauth_config["expires_at"] == 123
    assert cipher.decrypt_stored(oauth_config["client_secret"]) == "plaintext-client-secret"
    assert oauth_config["refresh_token"] == current_refresh
    assert cipher.decrypt_stored(repo_token) == "repo-token"
    assert cipher.decrypt_stored(identity_token) == "identity-token"


def test_envelope_normalization_wrong_key_rolls_back_revision(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260814_000002").returncode == 0

    credential_id = uuid4()
    wrong_key = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    legacy = _legacy_ciphertext("wrong-key-secret", key=wrong_key)
    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default)
            VALUES (%s, %s, 'model', 'wrong-key-model', %s, 'anthropic', 'anthropic', false)
            """,
            (credential_id, PROJECT_ID, Jsonb({"API_KEY": legacy})),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "wrong-key-model.data.API_KEY" in output

    with _connect(migration_database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        stored = connection.execute(
            "SELECT data->>'API_KEY' FROM joysafeter_credentials WHERE id = %s",
            (credential_id,),
        ).fetchone()[0]

    assert revision == "20260814_000002"
    assert stored == legacy


def test_head_normalizes_all_persisted_credential_references_to_public_ids(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    environment_id = uuid4()
    session_id = uuid4()
    agent_version_id = uuid4()
    model_credential_id = uuid4()
    service_credential_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        _seed_agent(
            connection,
            agent_id=agent_id,
            name="public-id-agent",
            secret_ref="model-secret",
        )
        connection.execute(
            """
            INSERT INTO joysafeter_secrets
                (id, project_id, name, provider, protocol, data, is_default)
            VALUES
                (%s, %s, 'model-secret', 'custom', 'custom', '{}'::jsonb, false),
                (%s, %s, 'service-secret', 'custom', 'custom', '{}'::jsonb, false)
            """,
            (
                model_credential_id,
                PROJECT_ID,
                service_credential_id,
                PROJECT_ID,
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_environments
                (id, project_id, name, description, image_version, config)
            VALUES (%s, %s, 'public-id-env', '', 0, %s)
            """,
            (
                environment_id,
                PROJECT_ID,
                Jsonb(
                    {
                        "secret_refs": ["service-secret"],
                        "egress_services": [
                            {
                                "name": "external",
                                "credential_ref": "service-secret",
                            }
                        ],
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "secret_ref": "model-secret",
                        "environment": {
                            "config": {
                                "secret_refs": [str(service_credential_id)],
                                "egress_services": [
                                    {
                                        "name": "external",
                                        "service_credential_id": str(service_credential_id),
                                    }
                                ],
                            }
                        },
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_agent_versions
                (id, agent_id, version, snapshot)
            VALUES (%s, %s, 1, %s)
            """,
            (
                agent_version_id,
                agent_id,
                Jsonb({"secret_ref": "model-secret"}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        environment_config = connection.execute(
            "SELECT config FROM joysafeter_environments WHERE id = %s",
            (environment_id,),
        ).fetchone()[0]
        session_snapshot = connection.execute(
            "SELECT agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()[0]
        version_snapshot = connection.execute(
            "SELECT snapshot FROM joysafeter_agent_versions WHERE id = %s",
            (agent_version_id,),
        ).fetchone()[0]

    model_public_id = f"cred_{model_credential_id}"
    service_public_id = f"cred_{service_credential_id}"
    assert environment_config["secret_refs"] == [service_public_id]
    assert environment_config["egress_services"][0]["service_credential_id"] == service_public_id
    assert "credential_ref" not in environment_config["egress_services"][0]
    assert session_snapshot["model_credential_id"] == model_public_id
    assert "secret_ref" not in session_snapshot
    frozen_config = session_snapshot["environment"]["config"]
    assert frozen_config["secret_refs"] == [service_public_id]
    assert frozen_config["egress_services"][0]["service_credential_id"] == service_public_id
    assert version_snapshot["model_credential_id"] == model_public_id
    assert "secret_ref" not in version_snapshot


def test_public_id_normalization_invalid_reference_rolls_back_all_rows(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260815_000001").returncode == 0
    valid_environment_id = uuid4()
    invalid_environment_id = uuid4()
    service_credential_id = uuid4()
    model_credential_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default)
            VALUES
                (%s, %s, 'service', 'valid-service', '{}'::jsonb, NULL, NULL, false),
                (%s, %s, 'model', 'wrong-kind-model', '{}'::jsonb, 'custom', 'custom', false)
            """,
            (
                service_credential_id,
                PROJECT_ID,
                model_credential_id,
                PROJECT_ID,
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_environments
                (id, project_id, name, description, image_version, config)
            VALUES
                (%s, %s, 'valid-before-invalid', '', 0, %s),
                (%s, %s, 'invalid-kind', '', 0, %s)
            """,
            (
                valid_environment_id,
                PROJECT_ID,
                Jsonb({"secret_refs": [str(service_credential_id)]}),
                invalid_environment_id,
                PROJECT_ID,
                Jsonb({"secret_refs": [str(model_credential_id)]}),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "must point to kind=service" in output
    assert str(invalid_environment_id) in output

    with _connect(migration_database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        valid_config = connection.execute(
            "SELECT config FROM joysafeter_environments WHERE id = %s",
            (valid_environment_id,),
        ).fetchone()[0]

    assert revision == "20260815_000001"
    assert valid_config["secret_refs"] == [str(service_credential_id)]


def test_public_id_normalization_preserves_deleted_service_identity_in_inactive_session_snapshot(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260815_000001").returncode == 0
    agent_id = uuid4()
    session_id = uuid4()
    service_credential_id = uuid4()
    mcp_credential_id = uuid4()
    mcp_group_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'inactive-history-agent', 'codex', '{}'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credential_groups (id, project_id, name)
            VALUES (%s, %s, 'legal-mcp-group')
            """,
            (mcp_group_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default,
                 mcp_server_url, normalized_mcp_server_url, credential_type, group_id,
                 deleted_at)
            VALUES
                (%s, %s, 'service', 'LEGAL_MCP', '{}'::jsonb, NULL, NULL, false,
                 NULL, NULL, NULL, NULL, now()),
                (%s, %s, 'mcp', 'LEGAL_MCP', '{}'::jsonb, NULL, NULL, false,
                 'https://ai-legal-test.example/legal-mcp/mcp',
                 'https://ai-legal-test.example/legal-mcp/mcp', 'bearer', %s, NULL)
            """,
            (
                service_credential_id,
                PROJECT_ID,
                mcp_credential_id,
                PROJECT_ID,
                mcp_group_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, archived_at, agent_snapshot)
            VALUES
                (%s, %s, %s, 'terminated', now(), %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "environment": {
                            "config": {
                                "egress_services": [
                                    {
                                        "name": "legal_mcp",
                                        "base_url": "https://ai-legal-test.example/legal-mcp/mcp",
                                        "credential_ref": "LEGAL_MCP",
                                    }
                                ]
                            }
                        }
                    }
                ),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        snapshot = connection.execute(
            "SELECT agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()[0]

    service = snapshot["environment"]["config"]["egress_services"][0]
    assert service["service_credential_id"] == f"cred_{service_credential_id}"
    assert "credential_ref" not in service


def test_public_id_normalization_rejects_deleted_service_in_active_session_snapshot(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260815_000001").returncode == 0
    agent_id = uuid4()
    session_id = uuid4()
    service_credential_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'active-history-agent', 'codex', '{}'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default, deleted_at)
            VALUES
                (%s, %s, 'service', 'LEGAL_MCP', '{}'::jsonb, NULL, NULL, false, now())
            """,
            (service_credential_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES
                (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "environment": {
                            "config": {
                                "egress_services": [
                                    {
                                        "name": "legal_mcp",
                                        "credential_ref": "LEGAL_MCP",
                                    }
                                ]
                            }
                        }
                    }
                ),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "points to a deleted credential" in output
    assert str(session_id) in output

    with _connect(migration_database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert revision == "20260815_000001"


def test_public_id_normalization_preserves_non_live_uuid_references_in_inactive_sessions(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260815_000001").returncode == 0
    agent_id = uuid4()
    deleted_session_id = uuid4()
    archived_session_id = uuid4()
    deleted_credential_id = uuid4()
    archived_credential_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'inactive-uuid-history-agent', 'codex', '{}'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default,
                 archived_at, deleted_at)
            VALUES
                (%s, %s, 'service', 'deleted-service', '{}'::jsonb, NULL, NULL, false,
                 NULL, now()),
                (%s, %s, 'service', 'archived-service', '{}'::jsonb, NULL, NULL, false,
                 now(), NULL)
            """,
            (
                deleted_credential_id,
                PROJECT_ID,
                archived_credential_id,
                PROJECT_ID,
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, archived_at, agent_snapshot)
            VALUES
                (%s, %s, %s, 'terminated', NULL, %s),
                (%s, %s, %s, 'idle', now(), %s)
            """,
            (
                deleted_session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "environment": {
                            "config": {
                                "secret_refs": [str(deleted_credential_id)],
                            }
                        }
                    }
                ),
                archived_session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "environment": {
                            "config": {
                                "secret_refs": [f"cred_{archived_credential_id}"],
                            }
                        }
                    }
                ),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        snapshots = dict(
            connection.execute(
                """
                SELECT id, agent_snapshot
                FROM joysafeter_sessions
                WHERE id IN (%s, %s)
                """,
                (deleted_session_id, archived_session_id),
            ).fetchall()
        )

    assert snapshots[deleted_session_id]["environment"]["config"]["secret_refs"] == [f"cred_{deleted_credential_id}"]
    assert snapshots[archived_session_id]["environment"]["config"]["secret_refs"] == [f"cred_{archived_credential_id}"]


def test_public_id_normalization_rejects_ambiguous_historical_name_in_inactive_session(
    migration_database: MigrationDatabase,
) -> None:
    assert _upgrade_to(migration_database, "20260815_000001").returncode == 0
    agent_id = uuid4()
    session_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'ambiguous-history-agent', 'codex', '{}'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (agent_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default, deleted_at)
            VALUES
                (%s, %s, 'service', 'LEGAL_MCP', '{}'::jsonb, NULL, NULL, false, now()),
                (%s, %s, 'service', 'LEGAL_MCP', '{}'::jsonb, NULL, NULL, false, now())
            """,
            (uuid4(), PROJECT_ID, uuid4(), PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, archived_at, agent_snapshot)
            VALUES
                (%s, %s, %s, 'terminated', now(), %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "environment": {
                            "config": {
                                "egress_services": [
                                    {
                                        "name": "legal_mcp",
                                        "credential_ref": "LEGAL_MCP",
                                    }
                                ]
                            }
                        }
                    }
                ),
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "must resolve exactly once, got 2: LEGAL_MCP" in output
    assert str(session_id) in output

    with _connect(migration_database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert revision == "20260815_000001"


def test_migration_rejects_skill_usage_without_a_concrete_version(
    migration_database: MigrationDatabase,
) -> None:
    usage_id = uuid4()
    with _connect(migration_database) as connection:
        connection.execute(
            """
            INSERT INTO joysafeter_skill_usage_log (id, skill_version)
            VALUES (%s, NULL)
            """,
            (usage_id,),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "skill_version" in output
    assert str(usage_id) in output


def test_mcp_contract_cutover_canonicalizes_every_persisted_surface(
    migration_database: MigrationDatabase,
) -> None:
    previous_revision = "20260823_000005"
    result = _upgrade_to(migration_database, previous_revision)
    assert result.returncode == 0, result.stderr

    agent_id = uuid4()
    environment_id = uuid4()
    agent_version_id = uuid4()
    session_id = uuid4()
    group_id = uuid4()
    bearer_credential_id = uuid4()
    oauth_credential_id = uuid4()

    with _connect(migration_database) as connection:
        _seed_project(connection)
        connection.execute(
            """
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                 agents, commands, permission_mode, metadata, version)
            VALUES
                (%s, %s, 'mcp-cutover-agent', 'codex', '{}'::jsonb, %s,
                 '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                 'default', '{}'::jsonb, 1)
            """,
            (
                agent_id,
                PROJECT_ID,
                Jsonb(
                    [
                        {
                            "type": "url",
                            "name": "remote",
                            "url": "https://mcp.example.test/rpc",
                        },
                        {
                            "type": "stdio",
                            "name": "local",
                            "command": "node",
                        },
                    ]
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_environments
                (id, project_id, name, description, image_version, config)
            VALUES (%s, %s, 'mcp-cutover-environment', '', 0, %s)
            """,
            (
                environment_id,
                PROJECT_ID,
                Jsonb(
                    {
                        "networking": {
                            "net_type": "limited",
                            "allowed_hosts": ["mcp.example.test"],
                            "allow_mcp_servers": True,
                        }
                    }
                ),
            ),
        )
        snapshot = {
            "mcp_servers": [
                {
                    "type": "streamable-http",
                    "name": "snapshot-remote",
                    "url": "https://snapshot.example.test/mcp",
                }
            ],
            "environment": {
                "config": {
                    "networking": {
                        "net_type": "unrestricted",
                        "allow_mcp_servers": False,
                    }
                }
            },
        }
        connection.execute(
            """
            INSERT INTO joysafeter_agent_versions (id, agent_id, version, snapshot)
            VALUES (%s, %s, 1, %s)
            """,
            (agent_version_id, agent_id, Jsonb(snapshot)),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_sessions
                (id, project_id, agent_id, status, agent_snapshot)
            VALUES (%s, %s, %s, 'idle', %s)
            """,
            (
                session_id,
                PROJECT_ID,
                agent_id,
                Jsonb(
                    {
                        "mcp_servers": [
                            {
                                "type": "http",
                                "name": "session-remote",
                                "url": "https://session.example.test/mcp",
                            }
                        ]
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credential_groups (id, project_id, name)
            VALUES (%s, %s, 'mcp-cutover-group')
            """,
            (group_id, PROJECT_ID),
        )
        connection.execute(
            """
            INSERT INTO joysafeter_credentials
                (id, project_id, kind, name, data, provider, protocol, is_default,
                 mcp_server_url, normalized_mcp_server_url, credential_type, group_id)
            VALUES
                (%s, %s, 'mcp', 'legacy-bearer', '{}'::jsonb, NULL, NULL, false,
                 'https://mcp.example.test/rpc', 'https://mcp.example.test/rpc',
                 'bearer', %s),
                (%s, %s, 'mcp', 'disabled-oauth', '{}'::jsonb, NULL, NULL, false,
                 'https://oauth.example.test/mcp', 'https://oauth.example.test/mcp',
                 'oauth', %s)
            """,
            (
                bearer_credential_id,
                PROJECT_ID,
                group_id,
                oauth_credential_id,
                PROJECT_ID,
                group_id,
            ),
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    assert result.returncode == 0, result.stderr

    with _connect(migration_database) as connection:
        agent_servers = connection.execute(
            "SELECT mcp_servers FROM joysafeter_agents WHERE id = %s",
            (agent_id,),
        ).fetchone()[0]
        environment_config = connection.execute(
            "SELECT config FROM joysafeter_environments WHERE id = %s",
            (environment_id,),
        ).fetchone()[0]
        version_snapshot = connection.execute(
            "SELECT snapshot FROM joysafeter_agent_versions WHERE id = %s",
            (agent_version_id,),
        ).fetchone()[0]
        session_snapshot = connection.execute(
            "SELECT agent_snapshot FROM joysafeter_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()[0]
        credential_types = dict(
            connection.execute(
                """
                SELECT id, credential_type
                FROM joysafeter_credentials
                WHERE id IN (%s, %s)
                """,
                (bearer_credential_id, oauth_credential_id),
            ).fetchall()
        )

    assert agent_servers == [
        {
            "type": "streamable_http",
            "name": "remote",
            "url": "https://mcp.example.test/rpc",
            "auth_requirement": "optional",
        },
        {"type": "local_stdio", "name": "local", "command": "node"},
    ]
    assert environment_config == {
        "networking": {
            "type": "limited",
            "allowed_hosts": ["mcp.example.test"],
        }
    }
    assert version_snapshot["mcp_servers"][0]["type"] == "streamable_http"
    assert version_snapshot["mcp_servers"][0]["auth_requirement"] == "optional"
    assert version_snapshot["environment"]["config"] == {"networking": {"type": "unrestricted"}}
    assert session_snapshot["mcp_servers"][0]["type"] == "streamable_http"
    assert session_snapshot["mcp_servers"][0]["auth_requirement"] == "optional"
    assert credential_types == {
        bearer_credential_id: "static_bearer",
        oauth_credential_id: "oauth",
    }


def test_mcp_contract_cutover_rejects_unknown_transport_atomically(
    migration_database: MigrationDatabase,
) -> None:
    previous_revision = "20260823_000005"
    result = _upgrade_to(migration_database, previous_revision)
    assert result.returncode == 0, result.stderr

    valid_agent_id = UUID(int=1)
    invalid_agent_id = UUID(int=2)
    with _connect(migration_database) as connection:
        _seed_project(connection)
        for agent_id, name, transport in (
            (valid_agent_id, "valid-before-invalid", "url"),
            (invalid_agent_id, "invalid-transport", "websocket"),
        ):
            connection.execute(
                """
                INSERT INTO joysafeter_agents
                    (id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                     agents, commands, permission_mode, metadata, version)
                VALUES
                    (%s, %s, %s, 'codex', '{}'::jsonb, %s, '[]'::jsonb,
                     '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'default', '{}'::jsonb, 1)
                """,
                (
                    agent_id,
                    PROJECT_ID,
                    name,
                    Jsonb(
                        [
                            {
                                "type": transport,
                                "name": name,
                                "url": "https://mcp.example.test/rpc",
                            }
                        ]
                    ),
                ),
            )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "unsupported MCP transport: 'websocket'" in output

    with _connect(migration_database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        valid_servers = connection.execute(
            "SELECT mcp_servers FROM joysafeter_agents WHERE id = %s",
            (valid_agent_id,),
        ).fetchone()[0]

    assert revision == previous_revision
    assert valid_servers[0]["type"] == "url"


def test_migrated_schema_matches_application_owned_metadata(
    migration_database: MigrationDatabase,
) -> None:
    upgrade = _upgrade_head(migration_database)
    assert upgrade.returncode == 0, upgrade.stderr

    check = subprocess.run(
        [ALEMBIC, "check"],
        cwd=BACKEND_ROOT,
        env=migration_database.env,
        capture_output=True,
        text=True,
    )

    assert check.returncode == 0, check.stdout + check.stderr
