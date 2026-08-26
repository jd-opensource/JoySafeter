"""Store tenant, authentication, and governed audit IDs as native UUIDs.

Revision ID: 20260825_000003
Revises: 20260825_000002
Create Date: 2026-08-25 00:00:03.000000
"""

from __future__ import annotations

from typing import NamedTuple, Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_000003"
down_revision: Union[str, None] = "20260825_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

BARE_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
LEGACY_COMPACT_UUID_SUFFIX = r"[0-9a-f]{32}"

UUID_COLUMNS: dict[str, tuple[str, ...]] = {
    "joysafeter_agents": ("project_id",),
    "joysafeter_api_keys": ("project_id", "org_id", "created_by"),
    "joysafeter_auth_sessions": ("id", "user_id", "active_organization_id"),
    "joysafeter_credential_access_audits": (
        "id",
        "project_id",
        "user_id",
        "org_id",
    ),
    "joysafeter_credential_groups": ("project_id",),
    "joysafeter_credentials": ("project_id",),
    "joysafeter_environments": ("project_id",),
    "joysafeter_files": ("project_id",),
    "joysafeter_memory_stores": ("project_id",),
    "joysafeter_oauth_account": ("id", "user_id"),
    "joysafeter_organization_members": ("id", "user_id", "organization_id"),
    "joysafeter_organization_projects": ("id", "org_id", "created_by_user_id"),
    "joysafeter_organizations": ("id",),
    "joysafeter_project_members": ("id", "project_id", "user_id"),
    "joysafeter_sandbox_network_policies": ("id",),
    "joysafeter_sandboxes": ("project_id",),
    "joysafeter_security_audit_logs": ("id", "user_id"),
    "joysafeter_session_storage_mounts": ("project_id",),
    "joysafeter_sessions": ("project_id",),
    "joysafeter_skill_security_scans": ("project_id", "owner_id", "created_by_id"),
    "joysafeter_skill_usage_log": ("project_id", "user_id"),
    "joysafeter_skill_versions": ("published_by_id", "approved_by_id"),
    "joysafeter_skills": ("owner_id", "created_by_id", "project_id"),
    "joysafeter_storage_mount_audit": ("project_id", "user_id"),
    "joysafeter_storage_organization_grants": ("org_id",),
    "joysafeter_storage_project_grants": ("project_id",),
    "joysafeter_task_identity_contexts": ("project_id", "user_id"),
    "joysafeter_tasks": ("project_id", "user_id", "org_id"),
    "joysafeter_triggers": ("project_id", "user_id", "org_id"),
    "joysafeter_users": ("id",),
}

PUBLIC_ID_PREFIXES: dict[tuple[str, str], str] = {
    ("joysafeter_agents", "project_id"): "proj_",
    ("joysafeter_api_keys", "project_id"): "proj_",
    ("joysafeter_api_keys", "org_id"): "org_",
    ("joysafeter_api_keys", "created_by"): "user_",
    ("joysafeter_auth_sessions", "id"): "authsess_",
    ("joysafeter_auth_sessions", "user_id"): "user_",
    ("joysafeter_auth_sessions", "active_organization_id"): "org_",
    ("joysafeter_credential_access_audits", "id"): "credaudit_",
    ("joysafeter_credential_access_audits", "project_id"): "proj_",
    ("joysafeter_credential_access_audits", "user_id"): "user_",
    ("joysafeter_credential_access_audits", "org_id"): "org_",
    ("joysafeter_credential_groups", "project_id"): "proj_",
    ("joysafeter_credentials", "project_id"): "proj_",
    ("joysafeter_environments", "project_id"): "proj_",
    ("joysafeter_files", "project_id"): "proj_",
    ("joysafeter_memory_stores", "project_id"): "proj_",
    ("joysafeter_oauth_account", "id"): "oauthacct_",
    ("joysafeter_oauth_account", "user_id"): "user_",
    ("joysafeter_organization_members", "id"): "orgmem_",
    ("joysafeter_organization_members", "user_id"): "user_",
    ("joysafeter_organization_members", "organization_id"): "org_",
    ("joysafeter_organization_projects", "id"): "proj_",
    ("joysafeter_organization_projects", "org_id"): "org_",
    ("joysafeter_organization_projects", "created_by_user_id"): "user_",
    ("joysafeter_organizations", "id"): "org_",
    ("joysafeter_project_members", "id"): "projmem_",
    ("joysafeter_project_members", "project_id"): "proj_",
    ("joysafeter_project_members", "user_id"): "user_",
    ("joysafeter_sandbox_network_policies", "id"): "sbxnetpol_",
    ("joysafeter_sandboxes", "project_id"): "proj_",
    ("joysafeter_security_audit_logs", "id"): "secaudit_",
    ("joysafeter_security_audit_logs", "user_id"): "user_",
    ("joysafeter_session_storage_mounts", "project_id"): "proj_",
    ("joysafeter_sessions", "project_id"): "proj_",
    ("joysafeter_skill_security_scans", "project_id"): "proj_",
    ("joysafeter_skill_security_scans", "owner_id"): "user_",
    ("joysafeter_skill_security_scans", "created_by_id"): "user_",
    ("joysafeter_skill_usage_log", "project_id"): "proj_",
    ("joysafeter_skill_usage_log", "user_id"): "user_",
    ("joysafeter_skill_versions", "published_by_id"): "user_",
    ("joysafeter_skill_versions", "approved_by_id"): "user_",
    ("joysafeter_skills", "owner_id"): "user_",
    ("joysafeter_skills", "created_by_id"): "user_",
    ("joysafeter_skills", "project_id"): "proj_",
    ("joysafeter_storage_mount_audit", "project_id"): "proj_",
    ("joysafeter_storage_mount_audit", "user_id"): "user_",
    ("joysafeter_storage_organization_grants", "org_id"): "org_",
    ("joysafeter_storage_project_grants", "project_id"): "proj_",
    ("joysafeter_task_identity_contexts", "project_id"): "proj_",
    ("joysafeter_task_identity_contexts", "user_id"): "user_",
    ("joysafeter_tasks", "project_id"): "proj_",
    ("joysafeter_tasks", "user_id"): "user_",
    ("joysafeter_tasks", "org_id"): "org_",
    ("joysafeter_triggers", "project_id"): "proj_",
    ("joysafeter_triggers", "user_id"): "user_",
    ("joysafeter_triggers", "org_id"): "org_",
    ("joysafeter_users", "id"): "user_",
}


class ForeignKeySpec(NamedTuple):
    name: str
    source_table: str
    target_table: str
    local_columns: tuple[str, ...]
    remote_columns: tuple[str, ...]
    ondelete: Optional[str] = None


FOREIGN_KEYS = (
    ForeignKeySpec(
        "fk_joysafeter_agents_project_id_joysafeter_organizat_0323e88f26",
        "joysafeter_agents",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_api_keys_project_org",
        "joysafeter_api_keys",
        "joysafeter_organization_projects",
        ("project_id", "org_id"),
        ("id", "org_id"),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_api_keys_created_by_joysafeter_users",
        "joysafeter_api_keys",
        "joysafeter_users",
        ("created_by",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_api_keys_org_id_joysafeter_organizations",
        "joysafeter_api_keys",
        "joysafeter_organizations",
        ("org_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_api_keys_project_id_joysafeter_organiz_c91dcf8ec0",
        "joysafeter_api_keys",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_auth_sessions_active_organization_id_j_9debc1202a",
        "joysafeter_auth_sessions",
        "joysafeter_organizations",
        ("active_organization_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_auth_sessions_user_id_joysafeter_users",
        "joysafeter_auth_sessions",
        "joysafeter_users",
        ("user_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_credential_groups_project_id_joysafeter_o_916c",
        "joysafeter_credential_groups",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_credentials_group_project",
        "joysafeter_credentials",
        "joysafeter_credential_groups",
        ("group_id", "project_id"),
        ("id", "project_id"),
        "RESTRICT",
    ),
    ForeignKeySpec(
        "fk_joysafeter_credentials_project_id_joysafeter_organiz_611a",
        "joysafeter_credentials",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_environments_project_id_joysafeter_org_d4176626fe",
        "joysafeter_environments",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_files_project_id_joysafeter_organization_projects",
        "joysafeter_files",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_memory_stores_project_id_joysafeter_or_7d59b8da80",
        "joysafeter_memory_stores",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_oauth_account_user_id_joysafeter_users",
        "joysafeter_oauth_account",
        "joysafeter_users",
        ("user_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_organization_members_organization_id_j_4b8586c925",
        "joysafeter_organization_members",
        "joysafeter_organizations",
        ("organization_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_organization_members_user_id_joysafeter_users",
        "joysafeter_organization_members",
        "joysafeter_users",
        ("user_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_projects_created_by_user",
        "joysafeter_organization_projects",
        "joysafeter_users",
        ("created_by_user_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_organization_projects_org_id_joysafete_b8f1c3feeb",
        "joysafeter_organization_projects",
        "joysafeter_organizations",
        ("org_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_project_members_project_id_joysafeter_2874b1b429",
        "joysafeter_project_members",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_project_members_user_id_joysafeter_users",
        "joysafeter_project_members",
        "joysafeter_users",
        ("user_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_sandboxes_project_id_joysafeter_organi_f2ef079275",
        "joysafeter_sandboxes",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_session_storage_mounts_project_id_joys_8a2d4f22b9",
        "joysafeter_session_storage_mounts",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_sessions_project_id_joysafeter_organiz_ad0a96f3fd",
        "joysafeter_sessions",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_skill_security_scans_created_by_id_joy_645cce72d6",
        "joysafeter_skill_security_scans",
        "joysafeter_users",
        ("created_by_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skill_security_scans_owner_id_joysafeter_users",
        "joysafeter_skill_security_scans",
        "joysafeter_users",
        ("owner_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skill_security_scans_project_id_joysaf_9599cf2b71",
        "joysafeter_skill_security_scans",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skill_versions_approved_by_id_joysafeter_users",
        "joysafeter_skill_versions",
        "joysafeter_users",
        ("approved_by_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skill_versions_published_by_id_joysafeter_users",
        "joysafeter_skill_versions",
        "joysafeter_users",
        ("published_by_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skills_created_by_id_joysafeter_users",
        "joysafeter_skills",
        "joysafeter_users",
        ("created_by_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skills_owner_id_joysafeter_users",
        "joysafeter_skills",
        "joysafeter_users",
        ("owner_id",),
        ("id",),
        "SET NULL",
    ),
    ForeignKeySpec(
        "fk_joysafeter_skills_project_id_joysafeter_organizat_e3294d7f80",
        "joysafeter_skills",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_storage_organization_grants_org_id_joy_759c9d48db",
        "joysafeter_storage_organization_grants",
        "joysafeter_organizations",
        ("org_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_storage_project_grants_project_id_joys_5e1b7df3e2",
        "joysafeter_storage_project_grants",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
        "CASCADE",
    ),
    ForeignKeySpec(
        "fk_joysafeter_tasks_project_id_joysafeter_organization_projects",
        "joysafeter_tasks",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
    ForeignKeySpec(
        "fk_joysafeter_triggers_project_id_joysafeter_organiz_afba10a3b6",
        "joysafeter_triggers",
        "joysafeter_organization_projects",
        ("project_id",),
        ("id",),
    ),
)


def _quote_identifier(identifier: str) -> str:
    if not identifier or not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def legacy_compact_prefix(table: str, column: str) -> str | None:
    if column == "project_id" or (table == "joysafeter_organization_projects" and column == "id"):
        return "proj-"
    if column in {"org_id", "organization_id", "active_organization_id"} or (
        table == "joysafeter_organizations" and column == "id"
    ):
        return "org-"
    return None


def invalid_uuid_count_sql(table: str, column: str) -> str:
    quoted_table = _quote_identifier(table)
    quoted_column = _quote_identifier(column)
    public_prefix = PUBLIC_ID_PREFIXES[(table, column)]
    public_pattern = f"^{public_prefix}{BARE_UUID_PATTERN[1:]}"
    public_clause = f" AND {quoted_column}::text !~* '{public_pattern}'"
    legacy_prefix = legacy_compact_prefix(table, column)
    legacy_clause = (
        f" AND {quoted_column}::text !~* '^{legacy_prefix}{LEGACY_COMPACT_UUID_SUFFIX}$'"
        if legacy_prefix is not None
        else ""
    )
    return (
        f"SELECT count(*) FROM {quoted_table} "
        f"WHERE {quoted_column} IS NOT NULL "
        f"AND {quoted_column}::text !~* '{BARE_UUID_PATTERN}'"
        f"{public_clause}"
        f"{legacy_clause}"
    )


def uuid_cast_expression(table: str, column: str) -> str:
    quoted_column = _quote_identifier(column)
    public_prefix = PUBLIC_ID_PREFIXES[(table, column)]
    public_pattern = f"^{public_prefix}{BARE_UUID_PATTERN[1:]}"
    public_suffix_start = len(public_prefix) + 1
    legacy_prefix = legacy_compact_prefix(table, column)
    if legacy_prefix is None:
        return (
            f"CASE WHEN {quoted_column}::text ~* '{public_pattern}' "
            f"THEN substring({quoted_column}::text FROM {public_suffix_start})::uuid "
            f"ELSE {quoted_column}::text::uuid END"
        )
    legacy_pattern = f"^{legacy_prefix}{LEGACY_COMPACT_UUID_SUFFIX}$"
    suffix_start = len(legacy_prefix) + 1
    return (
        f"CASE WHEN {quoted_column}::text ~* '{public_pattern}' "
        f"THEN substring({quoted_column}::text FROM {public_suffix_start})::uuid "
        f"WHEN {quoted_column}::text ~* '{legacy_pattern}' "
        f"THEN substring({quoted_column}::text FROM {suffix_start})::uuid "
        f"ELSE {quoted_column}::text::uuid END"
    )


def orphan_count_sql(foreign_key: ForeignKeySpec) -> str:
    source_table = _quote_identifier(foreign_key.source_table)
    target_table = _quote_identifier(foreign_key.target_table)
    join_condition = " AND ".join(
        f"source.{_quote_identifier(local)} = target.{_quote_identifier(remote)}"
        for local, remote in zip(
            foreign_key.local_columns,
            foreign_key.remote_columns,
            strict=True,
        )
    )
    non_null_condition = " AND ".join(
        f"source.{_quote_identifier(column)} IS NOT NULL" for column in foreign_key.local_columns
    )
    missing_target = f"target.{_quote_identifier(foreign_key.remote_columns[0])} IS NULL"
    return (
        f"SELECT count(*) FROM {source_table} AS source "
        f"LEFT JOIN {target_table} AS target ON {join_condition} "
        f"WHERE {non_null_condition} AND {missing_target}"
    )


def raise_for_preflight_failures(
    failures: list[tuple[str, str, int]],
) -> None:
    if not failures:
        return
    details = "; ".join(f"{table}.{column}: {count} invalid UUID values" for table, column, count in failures)
    raise RuntimeError(f"tenant/auth UUID migration preflight failed: {details}")


def credential_access_audit_compatibility_sql() -> tuple[str, ...]:
    return (
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS user_id VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS org_id VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS role VARCHAR(32)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS ip_address VARCHAR(255)",
        "ALTER TABLE joysafeter_credential_access_audits ADD COLUMN IF NOT EXISTS user_agent VARCHAR(1024)",
    )


def _ensure_credential_access_audit_columns() -> None:
    for statement in credential_access_audit_compatibility_sql():
        op.execute(statement)


def _preflight_uuid_values() -> None:
    connection = op.get_bind()
    invalid_values: list[tuple[str, str, int]] = []
    for table, columns in UUID_COLUMNS.items():
        for column in columns:
            invalid_count = connection.execute(sa.text(invalid_uuid_count_sql(table, column))).scalar_one()
            if invalid_count:
                invalid_values.append((table, column, invalid_count))
    raise_for_preflight_failures(invalid_values)


def _preflight_references() -> None:
    connection = op.get_bind()
    orphaned_references: list[str] = []
    for foreign_key in FOREIGN_KEYS:
        orphan_count = connection.execute(sa.text(orphan_count_sql(foreign_key))).scalar_one()
        if orphan_count:
            orphaned_references.append(f"{foreign_key.name}: {orphan_count} orphaned rows")
    if orphaned_references:
        raise RuntimeError("tenant/auth UUID referential preflight failed: " + "; ".join(orphaned_references))


def _drop_foreign_keys() -> None:
    for foreign_key in FOREIGN_KEYS:
        op.drop_constraint(
            foreign_key.name,
            foreign_key.source_table,
            type_="foreignkey",
        )


def _alter_columns(target_type: str) -> None:
    for table, columns in UUID_COLUMNS.items():
        for column in columns:
            quoted_table = _quote_identifier(table)
            quoted_column = _quote_identifier(column)
            using_expression = (
                uuid_cast_expression(table, column) if target_type == "uuid" else f"{quoted_column}::{target_type}"
            )
            op.execute(
                f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} TYPE {target_type} USING {using_expression}"
            )


def _create_foreign_keys() -> None:
    for foreign_key in FOREIGN_KEYS:
        options = {}
        if foreign_key.ondelete is not None:
            options["ondelete"] = foreign_key.ondelete
        op.create_foreign_key(
            foreign_key.name,
            foreign_key.source_table,
            foreign_key.target_table,
            list(foreign_key.local_columns),
            list(foreign_key.remote_columns),
            **options,
        )


def upgrade() -> None:
    _ensure_credential_access_audit_columns()
    _preflight_uuid_values()
    _preflight_references()
    op.execute("DELETE FROM joysafeter_auth_sessions")
    _drop_foreign_keys()
    _alter_columns("uuid")
    _create_foreign_keys()


def downgrade() -> None:
    _drop_foreign_keys()
    _alter_columns("text")
    _create_foreign_keys()
