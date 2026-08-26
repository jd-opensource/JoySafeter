from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

pytestmark = pytest.mark.no_db

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20260825_000003_type_tenant_auth_ids.py"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).with_name("alembic")
VAULT_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

TARGET_ID_TYPES = {
    "AuthSessionId",
    "CredentialAccessAuditId",
    "OAuthAccountId",
    "OrganizationId",
    "OrganizationMemberId",
    "ProjectId",
    "ProjectMemberId",
    "SandboxNetworkPolicyId",
    "SecurityAuditId",
    "UserId",
}


@dataclass(frozen=True)
class MigrationDatabase:
    dsn: str
    env: dict[str, str]


@pytest.fixture(scope="module")
def tenant_auth_postgres_server() -> Iterator[tuple[str, int]]:
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
        )


@pytest.fixture
def tenant_auth_migration_database(
    tenant_auth_postgres_server: tuple[str, int],
) -> Iterator[MigrationDatabase]:
    host, port = tenant_auth_postgres_server
    database_name = f"tenant_auth_ids_{uuid4().hex}"
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
    result = _upgrade_to(env, "20260825_000002")
    assert result.returncode == 0, result.stderr

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


def _upgrade_to(env: dict[str, str], revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _downgrade_to(env: dict[str, str], revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ALEMBIC, "downgrade", revision],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _insert_tenant_auth_fixture(
    connection: psycopg.Connection,
) -> dict[str, UUID]:
    ids = {
        "user": uuid4(),
        "organization": uuid4(),
        "other_organization": uuid4(),
        "project": uuid4(),
        "auth_session": uuid4(),
        "api_key": uuid4(),
    }
    connection.execute(
        """
        INSERT INTO joysafeter_users
            (id, name, email, email_verified, is_active, is_super_user,
             failed_login_attempts)
        VALUES (%s, 'Migration User', 'migration@example.com', true, true, false, 0)
        """,
        (str(ids["user"]),),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_organizations
            (id, name, slug, storage_used_bytes, departed_member_usage)
        VALUES
            (%s, 'Migration Organization', 'migration-org', 0, 0),
            (%s, 'Other Organization', 'other-org', 0, 0)
        """,
        (str(ids["organization"]), str(ids["other_organization"])),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_organization_projects
            (id, org_id, name, slug, is_default, created_by_user_id)
        VALUES (%s, %s, 'Migration Project', 'migration-project', true, %s)
        """,
        (str(ids["project"]), str(ids["organization"]), str(ids["user"])),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_api_keys
            (id, project_id, org_id, name, key_hash, key_prefix, created_by, role)
        VALUES (%s, %s, %s, 'Migration Key', 'migration-key-hash', 'jsk_test', %s, 'viewer')
        """,
        (
            ids["api_key"],
            str(ids["project"]),
            str(ids["organization"]),
            str(ids["user"]),
        ),
    )
    connection.execute(
        """
        INSERT INTO joysafeter_auth_sessions
            (id, expires_at, token, user_id, active_organization_id, is_trusted)
        VALUES (%s, now() + interval '1 day', 'migration-session-token', %s, %s, false)
        """,
        (
            str(ids["auth_session"]),
            str(ids["user"]),
            str(ids["organization"]),
        ),
    )
    connection.commit()
    return ids


def _migration_module():
    spec = importlib.util.spec_from_file_location("type_tenant_auth_ids", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_uuid_columns() -> dict[str, tuple[str, ...]]:
    import app.joysafeter_domain.models  # noqa: F401

    result: dict[str, tuple[str, ...]] = {}
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        columns = tuple(
            column.name
            for column in table.columns
            if isinstance(column.type, EntityIdType) and column.type.id_cls.__name__ in TARGET_ID_TYPES
        )
        if columns:
            result[table.name] = columns
    return result


def _expected_public_id_prefixes() -> dict[tuple[str, str], str]:
    return {
        (table_name, column_name): Base.metadata.tables[table_name].c[column_name].type.id_cls.prefix
        for table_name, column_names in _expected_uuid_columns().items()
        for column_name in column_names
    }


def _expected_foreign_keys() -> set[tuple[object, ...]]:
    selected_columns = {table: set(columns) for table, columns in _expected_uuid_columns().items()}
    result: set[tuple[object, ...]] = set()
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_key_constraints:
            local_columns = tuple(column.name for column in foreign_key.columns)
            remote_targets = tuple((element.column.table.name, element.column.name) for element in foreign_key.elements)
            local_is_selected = bool(set(local_columns) & selected_columns.get(table.name, set()))
            remote_is_selected = any(
                column in selected_columns.get(target_table, set()) for target_table, column in remote_targets
            )
            if not local_is_selected and not remote_is_selected:
                continue

            target_tables = {target_table for target_table, _ in remote_targets}
            assert len(target_tables) == 1
            result.add(
                (
                    table.name,
                    target_tables.pop(),
                    local_columns,
                    tuple(column for _, column in remote_targets),
                    foreign_key.ondelete,
                )
            )
    return result


def test_migration_revision_and_column_inventory_match_typed_models():
    migration = _migration_module()

    assert migration.revision == "20260825_000003"
    assert migration.down_revision == "20260825_000002"
    assert migration.UUID_COLUMNS == _expected_uuid_columns()
    assert sum(map(len, migration.UUID_COLUMNS.values())) == 57
    assert migration.PUBLIC_ID_PREFIXES == _expected_public_id_prefixes()


def test_migration_foreign_key_inventory_matches_typed_models():
    migration = _migration_module()

    assert all(len(foreign_key.name) <= 63 for foreign_key in migration.FOREIGN_KEYS)
    actual = {
        (
            foreign_key.source_table,
            foreign_key.target_table,
            foreign_key.local_columns,
            foreign_key.remote_columns,
            foreign_key.ondelete,
        )
        for foreign_key in migration.FOREIGN_KEYS
    }
    assert actual == _expected_foreign_keys()


def test_uuid_preflight_accepts_bare_uuid_and_matching_public_id_text():
    migration = _migration_module()

    assert re.fullmatch(
        migration.BARE_UUID_PATTERN,
        "018f6f42-0a51-7cc4-98c8-4f6f0ca5f010",
        flags=re.IGNORECASE,
    )
    assert not re.fullmatch(
        migration.BARE_UUID_PATTERN,
        "018f6f420a517cc498c84f6f0ca5f010",
        flags=re.IGNORECASE,
    )

    sql = migration.invalid_uuid_count_sql("joysafeter_users", "id")
    assert 'FROM "joysafeter_users"' in sql
    assert '"id" IS NOT NULL' in sql
    assert "user_[0-9a-f]{8}-[0-9a-f]{4}" in sql
    assert "!~*" in sql

    cast = migration.uuid_cast_expression("joysafeter_users", "id")
    assert 'substring("id"::text FROM 6)::uuid' in cast


def test_legacy_compact_tenant_ids_are_convertible_only_for_matching_columns():
    migration = _migration_module()

    project_preflight = migration.invalid_uuid_count_sql("joysafeter_organization_projects", "id")
    organization_preflight = migration.invalid_uuid_count_sql("joysafeter_organizations", "id")
    user_preflight = migration.invalid_uuid_count_sql("joysafeter_users", "id")

    assert "proj-[0-9a-f]{32}" in project_preflight
    assert "org-[0-9a-f]{32}" in organization_preflight
    assert "user-[0-9a-f]{32}" not in user_preflight

    project_cast = migration.uuid_cast_expression("joysafeter_tasks", "project_id")
    organization_cast = migration.uuid_cast_expression("joysafeter_tasks", "org_id")

    assert 'substring("project_id"::text FROM 6)::uuid' in project_cast
    assert 'substring("org_id"::text FROM 5)::uuid' in organization_cast


def test_uuid_preflight_failure_names_table_column_and_count():
    migration = _migration_module()

    with pytest.raises(
        RuntimeError,
        match=r"joysafeter_users\.id: 3 invalid UUID values",
    ):
        migration.raise_for_preflight_failures([("joysafeter_users", "id", 3)])


def test_missing_credential_access_audit_columns_are_restored():
    migration = _migration_module()

    statements = migration.credential_access_audit_compatibility_sql()

    assert statements == (
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS user_id VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS org_id VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS role VARCHAR(32)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS ip_address VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS user_agent VARCHAR(1024)",
    )


def test_referential_preflight_covers_api_key_composite_invariant():
    migration = _migration_module()

    api_key_foreign_key = next(
        foreign_key for foreign_key in migration.FOREIGN_KEYS if foreign_key.name == "fk_api_keys_project_org"
    )
    sql = migration.orphan_count_sql(api_key_foreign_key)

    assert 'source."project_id" = target."id"' in sql
    assert 'source."org_id" = target."org_id"' in sql
    assert 'source."project_id" IS NOT NULL' in sql
    assert 'source."org_id" IS NOT NULL' in sql


def test_upgrade_orders_preflight_drop_cast_recreate_and_session_invalidation(
    monkeypatch: pytest.MonkeyPatch,
):
    migration = _migration_module()
    operations: list[tuple[object, ...]] = []

    class ScalarResult:
        def scalar_one(self) -> int:
            return 0

    class Connection:
        def execute(self, statement):
            operations.append(("preflight", str(statement)))
            return ScalarResult()

    monkeypatch.setattr(migration.op, "get_bind", lambda: Connection())
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table_name, **kwargs: operations.append(("drop_constraint", name, table_name, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_foreign_key",
        lambda name, source_table, referent_table, local_cols, remote_cols, **kwargs: operations.append(
            (
                "create_foreign_key",
                name,
                source_table,
                referent_table,
                tuple(local_cols),
                tuple(remote_cols),
                kwargs,
            )
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: operations.append(("execute", str(statement))),
    )

    migration.upgrade()

    drop_indexes = [index for index, operation in enumerate(operations) if operation[0] == "drop_constraint"]
    alter_indexes = [
        index
        for index, operation in enumerate(operations)
        if operation[0] == "execute" and "ALTER COLUMN" in operation[1]
    ]
    create_indexes = [index for index, operation in enumerate(operations) if operation[0] == "create_foreign_key"]
    delete_indexes = [
        index
        for index, operation in enumerate(operations)
        if operation == ("execute", "DELETE FROM joysafeter_auth_sessions")
    ]

    assert len(drop_indexes) == len(migration.FOREIGN_KEYS)
    assert len(alter_indexes) == 57
    assert len(create_indexes) == len(migration.FOREIGN_KEYS)
    assert len(delete_indexes) == 1
    assert max(drop_indexes) < min(alter_indexes)
    assert max(alter_indexes) < min(create_indexes)
    assert delete_indexes[0] < min(drop_indexes)


def test_downgrade_never_restores_deleted_auth_sessions(monkeypatch: pytest.MonkeyPatch):
    migration = _migration_module()
    statements: list[str] = []

    monkeypatch.setattr(migration.op, "drop_constraint", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_foreign_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(str(statement)))

    migration.downgrade()

    assert any("TYPE text" in statement for statement in statements)
    assert not any("INSERT INTO joysafeter_auth_sessions" in statement for statement in statements)


def test_postgres_migration_converts_columns_preserves_constraints_and_deletes_sessions(
    tenant_auth_migration_database: MigrationDatabase,
):
    migration = _migration_module()
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        ids = _insert_tenant_auth_fixture(connection)

    result = _upgrade_to(tenant_auth_migration_database.env, "head")
    assert result.returncode == 0, result.stderr

    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        for table, columns in migration.UUID_COLUMNS.items():
            actual_types = dict(
                connection.execute(
                    """
                    SELECT column_name, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                      AND column_name = ANY(%s)
                    """,
                    (table, list(columns)),
                ).fetchall()
            )
            assert actual_types == dict.fromkeys(columns, "uuid")

        assert connection.execute(
            "SELECT id, org_id, created_by_user_id FROM joysafeter_organization_projects"
        ).fetchone() == (
            ids["project"],
            ids["organization"],
            ids["user"],
        )
        assert connection.execute("SELECT count(*) FROM joysafeter_auth_sessions").fetchone()[0] == 0

        constraint_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE contype = 'f'
                """
            ).fetchall()
        }
        assert {foreign_key.name for foreign_key in migration.FOREIGN_KEYS} <= constraint_names
        assert (
            connection.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'uq_joysafeter_organization_projects_id_org'
                  AND contype = 'u'
                """
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                """
                SELECT count(*)
                FROM pg_indexes
                WHERE indexname = 'ix_api_keys_active_project_created_id'
                """
            ).fetchone()[0]
            == 1
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "UPDATE joysafeter_api_keys SET org_id = %s WHERE id = %s",
                (ids["other_organization"], ids["api_key"]),
            )
        connection.rollback()

    result = _downgrade_to(
        tenant_auth_migration_database.env,
        "20260825_000002",
    )
    assert result.returncode == 0, result.stderr

    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        assert (
            connection.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'joysafeter_users' AND column_name = 'id'"
            ).fetchone()[0]
            == "text"
        )
        assert connection.execute("SELECT id FROM joysafeter_users").fetchone()[0] == str(ids["user"])
        assert connection.execute("SELECT count(*) FROM joysafeter_auth_sessions").fetchone()[0] == 0


def test_postgres_migration_accepts_matching_canonical_public_values(
    tenant_auth_migration_database: MigrationDatabase,
):
    user_uuid = uuid4()
    public_user_id = f"user_{user_uuid}"
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        connection.execute(
            """
            INSERT INTO joysafeter_users
                (id, name, email, email_verified, is_active, is_super_user,
                 failed_login_attempts)
            VALUES (%s, 'Invalid User', 'invalid@example.com', true, true, false, 0)
            """,
            (public_user_id,),
        )
        connection.commit()

    result = _upgrade_to(tenant_auth_migration_database.env, "head")

    assert result.returncode == 0, result.stderr
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        assert connection.execute("SELECT id FROM joysafeter_users").fetchone()[0] == user_uuid


def test_postgres_migration_rejects_wrong_public_id_prefix(
    tenant_auth_migration_database: MigrationDatabase,
):
    wrong_user_id = f"org_{uuid4()}"
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        connection.execute(
            """
            INSERT INTO joysafeter_users
                (id, name, email, email_verified, is_active, is_super_user,
                 failed_login_attempts)
            VALUES (%s, 'Invalid User', 'invalid@example.com', true, true, false, 0)
            """,
            (wrong_user_id,),
        )
        connection.commit()

    result = _upgrade_to(tenant_auth_migration_database.env, "head")

    assert result.returncode != 0
    assert "joysafeter_users.id: 1 invalid UUID values" in result.stderr
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260825_000002"


def test_postgres_migration_rejects_api_key_project_org_mismatch(
    tenant_auth_migration_database: MigrationDatabase,
):
    migration = _migration_module()
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        ids = _insert_tenant_auth_fixture(connection)
        connection.execute("ALTER TABLE joysafeter_api_keys DROP CONSTRAINT fk_api_keys_project_org")
        connection.execute(
            "UPDATE joysafeter_api_keys SET org_id = %s WHERE id = %s",
            (str(ids["other_organization"]), ids["api_key"]),
        )
        connection.commit()

    result = _upgrade_to(tenant_auth_migration_database.env, "head")

    assert result.returncode != 0
    assert "fk_api_keys_project_org: 1 orphaned rows" in result.stderr
    with psycopg.connect(tenant_auth_migration_database.dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260825_000002"
        assert connection.execute("SELECT count(*) FROM joysafeter_auth_sessions").fetchone()[0] == 1
        assert len(migration.FOREIGN_KEYS) == 35
