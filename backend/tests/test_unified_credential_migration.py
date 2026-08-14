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

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC = Path(sys.executable).with_name("alembic")
PRE_UNIFIED_REVISION = "20260803_000001"
PROJECT_ID = "proj-migration"
ORG_ID = "org-migration"


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
    return subprocess.run(
        [ALEMBIC, "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=database.env,
        capture_output=True,
        text=True,
    )


def _connect(database: MigrationDatabase) -> psycopg.Connection:
    return psycopg.connect(database.dsn)


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
) -> None:
    connection.execute(
        """
        INSERT INTO joysafeter_vaults (id, project_id, name, description)
        VALUES (%s, %s, %s, '')
        """,
        (vault_id, PROJECT_ID, name),
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


def test_migration_renames_mcp_configs_without_changing_values(
    migration_database: MigrationDatabase,
) -> None:
    agent_id = uuid4()
    mcp_configs = [{"name": "github", "url": "https://mcp.example.test", "enabled": True}]
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
    assert stored_value == mcp_configs


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
            token="enc:first",
        )
        _seed_vault_credential(
            connection,
            credential_id=second_credential_id,
            vault_id=vault_id,
            name="second",
            url="https://mcp.example.test",
            token="enc:second",
        )
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "normalized MCP server URL collisions" in output
    assert str(first_credential_id) in output
    assert str(second_credential_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
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
            token="enc:older",
            created_at="2026-08-13T10:00:00Z",
        )
        _seed_vault_credential(
            connection,
            credential_id=newer_credential_id,
            vault_id=newer_vault_id,
            name="shared-name",
            url="https://newer.example.test",
            token="enc:newer",
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

    assert rows == [
        (older_credential_id, f"shared-name (migrated-dup {older_credential_id})", "enc:older"),
        (newer_credential_id, "shared-name", "enc:newer"),
    ]


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
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
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
        connection.commit()

    result = _upgrade_head(migration_database)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "malformed legacy credential reference JSON" in output
    assert str(environment_id) in output
    assert str(session_id) in output
    with _connect(migration_database) as connection:
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
    assert target_exists is None


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
    assert snapshot["model_credential_id"] == str(secret_id)
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
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
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
