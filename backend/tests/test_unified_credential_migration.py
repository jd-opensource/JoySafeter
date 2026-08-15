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
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
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
        target_exists = connection.execute(
            "SELECT to_regclass('joysafeter_credentials')"
        ).fetchone()[0]
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
