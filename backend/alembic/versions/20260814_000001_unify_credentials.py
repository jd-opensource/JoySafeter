"""unify secrets + vaults into joysafeter_credentials (forward, data-preserving)

Revision ID: 20260814_000001
Revises: 20260803_000001
Create Date: 2026-08-14 00:00:00.000000

WHY THIS MIGRATION EXISTS
=========================
The unified-credential refactor originally squashed the whole schema into a
single ``initial_schema`` migration whose revision id (``20260803_000001``)
COLLIDES with the live production head on ``joysafeter-v2-ha`` (the
``cleanup_schema_after_squash`` revision, same id). Running that squash against
the deployed database is a silent no-op (alembic thinks it is already at head),
so the unified schema would never be created and existing secrets/vaults would
never be migrated.

This migration is the prod-safe alternative: a FORWARD delta whose
``down_revision`` is the real production head. It:

  1. creates joysafeter_credential_groups / joysafeter_credentials /
     joysafeter_session_credential_groups,
  2. adds the id-based reference columns on agents/triggers,
  3. BACKFILLS every historical row: vaults -> groups, vault_credentials ->
     mcp credentials, secrets -> model/service credentials, and rewrites every
     name-based reference to an id-based one (agents, triggers, sessions,
     environment config JSON, active-session agent_snapshot JSON),
  4. drops the legacy columns and tables.

Encrypted material (``token_value`` and secret ``data``) is carried over
verbatim: CredentialCipher reads the legacy no-version ``enc:`` envelope, so no
re-encryption is needed.

OPERATOR DECISIONS ENCODED HERE (review before running on prod)
---------------------------------------------------------------
* NULL project_id: the new tables require project_id NOT NULL. Any legacy
  secret/vault with a NULL project_id ABORTS the migration with an explicit list
  (we refuse to invent a project or silently drop data). Assign a project first.
* kind inference for a secret: 'model' if it is referenced by any model slot,
  marked as the default model secret, OR its provider is a real provider (not
  the 'custom' default); otherwise 'service'. Service credentials must have
  NULL provider/protocol (CHECK), so we clear those two columns for them.
* duplicate (project_id, name): the legacy schema allowed duplicate secret names
  (resolution was "latest created_at wins"). The new partial unique index
  forbids duplicates among non-deleted rows, so older same-name rows are kept
  (no data loss) but their name is suffixed "(migrated-dup <shortid>)". The
  latest row keeps the original name and is what references resolve to.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op
from app.joysafeter_shared.mcp_url import normalize_mcp_url

revision: str = "20260814_000001"
down_revision: Union[str, None] = "20260803_000001"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


# --------------------------------------------------------------------------- #
# schema creation
# --------------------------------------------------------------------------- #
def _create_tables() -> None:
    op.create_table(
        "joysafeter_credential_groups",
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_joysafeter_credential_groups")),
        sa.UniqueConstraint("id", "project_id", name="uq_credential_groups_id_project"),
    )
    op.create_index(
        op.f("ix_joysafeter_credential_groups_project_id"),
        "joysafeter_credential_groups",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "uq_credential_groups_project_name",
        "joysafeter_credential_groups",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "joysafeter_credentials",
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("protocol", sa.String(length=64), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mcp_server_url", sa.Text(), nullable=True),
        sa.Column("normalized_mcp_server_url", sa.Text(), nullable=True),
        sa.Column("credential_type", sa.Text(), nullable=True),
        sa.Column("oauth_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(kind = 'model' AND provider IS NOT NULL AND protocol IS NOT NULL "
            "AND mcp_server_url IS NULL AND normalized_mcp_server_url IS NULL "
            "AND credential_type IS NULL AND oauth_config IS NULL AND group_id IS NULL) OR "
            "(kind = 'mcp' AND mcp_server_url IS NOT NULL "
            "AND normalized_mcp_server_url IS NOT NULL AND credential_type IS NOT NULL "
            "AND group_id IS NOT NULL "
            "AND provider IS NULL AND protocol IS NULL AND is_default = false) OR "
            "(kind = 'service' AND provider IS NULL AND protocol IS NULL "
            "AND mcp_server_url IS NULL AND normalized_mcp_server_url IS NULL "
            "AND credential_type IS NULL AND oauth_config IS NULL "
            "AND group_id IS NULL AND is_default = false)",
            name="kind_identity",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_joysafeter_credentials")),
    )
    op.create_index(op.f("ix_joysafeter_credentials_project_id"), "joysafeter_credentials", ["project_id"], unique=False)
    op.create_index("ix_joysafeter_credentials_group_id", "joysafeter_credentials", ["group_id"], unique=False)
    op.create_index(
        "uq_credentials_project_kind_name",
        "joysafeter_credentials",
        ["project_id", "kind", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_credentials_default_protocol",
        "joysafeter_credentials",
        ["project_id", "protocol"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND kind = 'model' AND archived_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_credentials_group_url",
        "joysafeter_credentials",
        ["group_id", "normalized_mcp_server_url"],
        unique=True,
        postgresql_where=sa.text("kind = 'mcp' AND deleted_at IS NULL"),
    )

    op.create_table(
        "joysafeter_session_credential_groups",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("credential_group_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint(
            "session_id", "credential_group_id", name=op.f("pk_joysafeter_session_credential_groups")
        ),
    )


def _add_reference_columns() -> None:
    op.add_column("joysafeter_agents", sa.Column("model_credential_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_joysafeter_agents_model_credential_id"),
        "joysafeter_agents",
        ["model_credential_id"],
        unique=False,
    )
    op.add_column("joysafeter_triggers", sa.Column("webhook_auth_credential_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("webhook_auth_field", sa.String(length=255), nullable=True))
    op.create_index(
        op.f("ix_joysafeter_triggers_webhook_auth_credential_id"),
        "joysafeter_triggers",
        ["webhook_auth_credential_id"],
        unique=False,
    )


def _add_foreign_keys() -> None:
    op.create_foreign_key(
        op.f("fk_joysafeter_credential_groups_project_id_joysafeter_organization_projects"),
        "joysafeter_credential_groups",
        "joysafeter_organization_projects",
        ["project_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_credentials_project_id_joysafeter_organization_projects"),
        "joysafeter_credentials",
        "joysafeter_organization_projects",
        ["project_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_credentials_group_project",
        "joysafeter_credentials",
        "joysafeter_credential_groups",
        ["group_id", "project_id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agents_model_credential",
        "joysafeter_agents",
        "joysafeter_credentials",
        ["model_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_triggers_webhook_auth_credential",
        "joysafeter_triggers",
        "joysafeter_credentials",
        ["webhook_auth_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_session_credential_groups_session",
        "joysafeter_session_credential_groups",
        "joysafeter_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_session_credential_groups_group",
        "joysafeter_session_credential_groups",
        "joysafeter_credential_groups",
        ["credential_group_id"],
        ["id"],
        ondelete="RESTRICT",
    )


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _reference(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _secret_is_model(is_default, project_id, name, provider, model_reference_names) -> bool:
    # Single source of truth for kind inference, shared by the pre-flight guard
    # and the backfill so they can never disagree (a divergence here silently
    # mis-classifies a secret and strands its references).
    return bool(is_default) or (project_id, name) in model_reference_names or (
        provider is not None and provider not in ("custom", "")
    )


def _abort_on_null_project(conn) -> None:
    problems = {}
    for table in ("joysafeter_secrets", "joysafeter_vaults"):
        rows = conn.execute(sa.text(f"SELECT id FROM {table} WHERE project_id IS NULL")).fetchall()
        if rows:
            problems[table] = [str(r[0]) for r in rows]
    if problems:
        raise RuntimeError(
            "Cannot migrate: the new credential tables require project_id NOT NULL, "
            "but these legacy rows have a NULL project_id. Assign a project to them "
            f"and re-run. Offending rows: {problems}"
        )


def _abort_on_malformed_reference_json(conn) -> None:
    problems = {}

    for row in conn.execute(
        sa.text("SELECT id, config FROM joysafeter_environments WHERE config IS NOT NULL")
    ).fetchall():
        config = _json_value(row.config, None)
        issues = []
        if not isinstance(config, dict):
            issues.append("config must be a JSON object")
        else:
            if "secret_refs" in config:
                refs = config["secret_refs"]
                if not isinstance(refs, list):
                    issues.append("config.secret_refs must be a JSON array")
                elif any(_reference(value) is None for value in refs):
                    issues.append("config.secret_refs entries must be non-empty strings")

            if "egress_services" in config:
                services = config["egress_services"]
                if not isinstance(services, list):
                    issues.append("config.egress_services must be a JSON array")
                else:
                    for index, service in enumerate(services):
                        if not isinstance(service, dict):
                            issues.append(f"config.egress_services[{index}] must be a JSON object")
                            continue
                        if (
                            "credential_ref" in service
                            and not service.get("service_credential_id")
                            and _reference(service["credential_ref"]) is None
                        ):
                            issues.append(
                                f"config.egress_services[{index}].credential_ref "
                                "must be a non-empty string"
                            )

        if issues:
            problems.setdefault("environments.config", []).append(
                {"owner_id": str(row.id), "issues": issues}
            )

    for row in conn.execute(
        sa.text(
            "SELECT id, vault_ids, agent_snapshot FROM joysafeter_sessions "
            "WHERE vault_ids IS NOT NULL OR agent_snapshot IS NOT NULL"
        )
    ).fetchall():
        issues = []
        if row.vault_ids is not None:
            vault_ids = _json_value(row.vault_ids, None)
            if not isinstance(vault_ids, list):
                issues.append("vault_ids must be a JSON array")
            elif any(_reference(value) is None for value in vault_ids):
                issues.append("vault_ids entries must be non-empty UUID strings")

        if row.agent_snapshot is not None:
            snapshot = _json_value(row.agent_snapshot, None)
            if not isinstance(snapshot, dict):
                issues.append("agent_snapshot must be a JSON object")
            elif (
                "secret_ref" in snapshot
                and not snapshot.get("model_credential_id")
                and _reference(snapshot["secret_ref"]) is None
            ):
                issues.append("agent_snapshot.secret_ref must be a non-empty string")

        if issues:
            problems.setdefault("sessions", []).append(
                {"owner_id": str(row.id), "issues": issues}
            )

    if problems:
        raise RuntimeError(
            "Cannot migrate malformed legacy credential reference JSON. "
            f"Repair these rows before retrying: {problems}"
        )


def _abort_on_mcp_normalization_conflicts(conn) -> None:
    credentials_by_endpoint = defaultdict(list)
    invalid_urls = []
    rows = conn.execute(
        sa.text(
            "SELECT id, vault_id, mcp_server_url FROM joysafeter_vault_credentials "
            "WHERE deleted_at IS NULL ORDER BY vault_id, id"
        )
    ).fetchall()
    for row in rows:
        try:
            normalized_url = normalize_mcp_url(row.mcp_server_url)
        except (TypeError, ValueError) as exc:
            invalid_urls.append(
                {
                    "id": str(row.id),
                    "vault_id": str(row.vault_id),
                    "mcp_server_url": row.mcp_server_url,
                    "error": str(exc),
                }
            )
            continue
        credentials_by_endpoint[(str(row.vault_id), normalized_url)].append(str(row.id))

    collisions = [
        {
            "vault_id": vault_id,
            "normalized_mcp_server_url": normalized_url,
            "credential_ids": credential_ids,
        }
        for (vault_id, normalized_url), credential_ids in credentials_by_endpoint.items()
        if len(credential_ids) > 1
    ]
    if invalid_urls or collisions:
        raise RuntimeError(
            "Cannot migrate legacy MCP credentials with invalid URLs or normalized MCP server URL collisions. "
            f"Repair these rows before retrying: invalid_urls={invalid_urls}, collisions={collisions}"
        )


def _collect_legacy_references(conn):
    model_references = []
    service_references = []
    vault_references = []

    for row in conn.execute(
        sa.text(
            "SELECT id, project_id, secret_ref FROM joysafeter_agents "
            "WHERE secret_ref IS NOT NULL AND btrim(secret_ref) <> ''"
        )
    ).fetchall():
        model_references.append(("agents.secret_ref", str(row.id), row.project_id, row.secret_ref.strip()))

    for row in conn.execute(
        sa.text(
            "SELECT id, project_id, secret_ref FROM joysafeter_triggers "
            "WHERE secret_ref IS NOT NULL AND btrim(secret_ref) <> ''"
        )
    ).fetchall():
        service_references.append(("triggers.secret_ref", str(row.id), row.project_id, row.secret_ref.strip()))

    for row in conn.execute(
        sa.text("SELECT id, project_id, config FROM joysafeter_environments WHERE config IS NOT NULL")
    ).fetchall():
        config = _json_value(row.config, {})
        if not isinstance(config, dict):
            continue

        refs = config.get("secret_refs")
        if isinstance(refs, list):
            for value in refs:
                ref = _reference(value)
                if ref:
                    service_references.append(
                        ("environments.config.secret_refs", str(row.id), row.project_id, ref)
                    )

        services = config.get("egress_services")
        if isinstance(services, list):
            for service in services:
                if not isinstance(service, dict) or service.get("service_credential_id"):
                    continue
                ref = _reference(service.get("credential_ref"))
                if ref:
                    service_references.append(
                        (
                            "environments.config.egress_services[].credential_ref",
                            str(row.id),
                            row.project_id,
                            ref,
                        )
                    )

    for row in conn.execute(
        sa.text(
            "SELECT id, project_id, vault_ids, agent_snapshot FROM joysafeter_sessions "
            "WHERE vault_ids IS NOT NULL OR agent_snapshot IS NOT NULL"
        )
    ).fetchall():
        vault_ids = _json_value(row.vault_ids, [])
        if isinstance(vault_ids, list):
            for value in vault_ids:
                ref = _reference(value)
                if ref:
                    vault_references.append(("sessions.vault_ids", str(row.id), row.project_id, ref))

        snapshot = _json_value(row.agent_snapshot, {})
        if isinstance(snapshot, dict) and not snapshot.get("model_credential_id"):
            ref = _reference(snapshot.get("secret_ref"))
            if ref:
                model_references.append(
                    ("sessions.agent_snapshot.secret_ref", str(row.id), row.project_id, ref)
                )

    return model_references, service_references, vault_references


def _abort_on_ambiguous_or_unresolved_references(conn) -> None:
    model_references, service_references, vault_references = _collect_legacy_references(conn)
    model_keys = {(project_id, name) for _, _, project_id, name in model_references}
    service_keys = {(project_id, name) for _, _, project_id, name in service_references}

    secret_rows = conn.execute(
        sa.text(
            """
            SELECT id, project_id, name, provider, is_default
            FROM joysafeter_secrets
            WHERE deleted_at IS NULL
            ORDER BY project_id, name, created_at, id
            """
        )
    ).fetchall()
    latest_secret_by_name = {(row.project_id, row.name): row for row in secret_rows}

    cross_consumer_keys = {
        key for key in model_keys & service_keys if key in latest_secret_by_name
    }
    if cross_consumer_keys:
        offending = [
            {
                "id": str(latest_secret_by_name[key].id),
                "project_id": key[0],
                "name": key[1],
            }
            for key in sorted(cross_consumer_keys, key=lambda value: (str(value[0]), value[1]))
        ]
        raise RuntimeError(
            "Cannot migrate: a legacy secret is consumed as both model and service material. "
            f"Split or reassign these references before retrying: {offending}"
        )

    unresolved = {}
    for expected_kind, references in (("model", model_references), ("service", service_references)):
        for source, owner_id, project_id, name in references:
            secret = latest_secret_by_name.get((project_id, name))
            actual_kind = None
            if secret is not None:
                is_model = _secret_is_model(
                    secret.is_default, project_id, name, secret.provider, model_keys
                )
                actual_kind = "model" if is_model else "service"
            if secret is None or actual_kind != expected_kind:
                unresolved.setdefault(source, []).append(
                    {
                        "owner_id": owner_id,
                        "project_id": project_id,
                        "reference": name,
                    }
                )

    vault_projects = {
        str(row.id): row.project_id
        for row in conn.execute(sa.text("SELECT id, project_id FROM joysafeter_vaults")).fetchall()
    }
    for source, owner_id, project_id, vault_id in vault_references:
        if vault_projects.get(vault_id) != project_id:
            unresolved.setdefault(source, []).append(
                {
                    "owner_id": owner_id,
                    "project_id": project_id,
                    "reference": vault_id,
                }
            )

    if unresolved:
        raise RuntimeError(
            "Cannot migrate unresolved legacy credential references. "
            f"Fix every reference before retrying: {unresolved}"
        )


def _abort_on_duplicate_default_model_protocol(conn) -> None:
    """uq_credentials_default_protocol allows only one default model credential
    per (project_id, protocol). Legacy joysafeter_secrets had no such constraint,
    so two default secrets on the same protocol would fail the unique index
    mid-backfill. Detect it up front, using the SAME kind inference as the
    backfill (is_default itself makes the secret a model credential)."""

    by_protocol = defaultdict(list)
    for row in conn.execute(
        sa.text(
            "SELECT id, project_id, protocol FROM joysafeter_secrets "
            "WHERE deleted_at IS NULL AND is_default = true"
        )
    ).fetchall():
        by_protocol[(row.project_id, row.protocol)].append(str(row.id))

    collisions = [
        {"project_id": project_id, "protocol": protocol, "secret_ids": ids}
        for (project_id, protocol), ids in by_protocol.items()
        if len(ids) > 1
    ]
    if collisions:
        raise RuntimeError(
            "Cannot migrate: multiple default model secrets share a (project, protocol); "
            f"only one default is allowed per protocol. Resolve before retrying: {collisions}"
        )


def _abort_on_invalid_skill_usage_ids(conn) -> None:
    missing_versions = conn.execute(
        sa.text("SELECT id FROM joysafeter_skill_usage_log WHERE skill_version IS NULL")
    ).fetchall()
    if missing_versions:
        raise RuntimeError(
            "Cannot migrate skill usage rows without a concrete skill_version. "
            f"Repair these rows before retrying: {[str(row.id) for row in missing_versions]}"
        )

    uuid_pattern = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    invalid = {}
    for column, prefix in (("session_id", "sess_"), ("agent_id", "agent_")):
        rows = conn.execute(
            sa.text(
                f"SELECT id, {column} FROM joysafeter_skill_usage_log "
                f"WHERE {column} IS NOT NULL AND {column} !~* :pattern"
            ),
            {"pattern": f"^({prefix})?{uuid_pattern}$"},
        ).fetchall()
        if rows:
            invalid[f"joysafeter_skill_usage_log.{column}"] = [
                {"id": str(row.id), "value": row[1]} for row in rows
            ]
    if invalid:
        raise RuntimeError(
            "Cannot migrate invalid legacy typed IDs. Repair these values before retrying: "
            f"{invalid}"
        )


def _rename_agent_mcp_configs() -> None:
    op.alter_column("joysafeter_agents", "mcp_configs", new_column_name="mcp_servers")


def _align_skill_usage_id_types() -> None:
    op.alter_column(
        "joysafeter_skill_usage_log",
        "skill_version",
        existing_type=sa.String(length=64),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        "joysafeter_skill_usage_log",
        "session_id",
        existing_type=sa.String(length=255),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using=(
            "CASE WHEN session_id LIKE 'sess_%' THEN substring(session_id FROM 6)::uuid "
            "ELSE session_id::uuid END"
        ),
    )
    op.alter_column(
        "joysafeter_skill_usage_log",
        "agent_id",
        existing_type=sa.String(length=255),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using=(
            "CASE WHEN agent_id LIKE 'agent_%' THEN substring(agent_id FROM 7)::uuid "
            "ELSE agent_id::uuid END"
        ),
    )


# --------------------------------------------------------------------------- #
# backfill
# --------------------------------------------------------------------------- #
def _backfill(conn) -> None:
    # 1) vaults -> credential_groups (reuse the vault id as the group id) --------
    conn.execute(
        sa.text(
            """
            INSERT INTO joysafeter_credential_groups
                (id, project_id, name, description, archived_at, deleted_at, created_at, updated_at)
            SELECT id, project_id, name, COALESCE(description, ''),
                   archived_at, deleted_at, created_at, updated_at
            FROM joysafeter_vaults
            """
        )
    )

    # 2) vault_credentials -> credentials(kind='mcp') --------------------------
    #    normalized_mcp_server_url must match the app's normalizer, so compute it
    #    per row in Python rather than in SQL.
    vc_rows = conn.execute(
        sa.text(
            """
            SELECT c.id, v.project_id, c.name, c.credential_type, c.mcp_server_url,
                   c.token_value, c.oauth_config, c.vault_id, c.archived_at, c.deleted_at,
                   c.created_at, c.updated_at
            FROM joysafeter_vault_credentials c
            JOIN joysafeter_vaults v ON v.id = c.vault_id
            ORDER BY v.project_id, c.name, c.created_at, c.id
            """
        )
    ).fetchall()

    latest_live_mcp_by_name = {}
    occupied_live_mcp_names = defaultdict(set)
    for row in vc_rows:
        if row.deleted_at is None:
            key = (row.project_id, row.name)
            latest_live_mcp_by_name[key] = str(row.id)
            occupied_live_mcp_names[row.project_id].add(row.name)

    for r in vc_rows:
        name = r.name
        if (
            r.deleted_at is None
            and latest_live_mcp_by_name[(r.project_id, r.name)] != str(r.id)
        ):
            name = f"{r.name} (migrated-dup {r.id})"
            suffix = 2
            while name in occupied_live_mcp_names[r.project_id]:
                name = f"{r.name} (migrated-dup {r.id}-{suffix})"
                suffix += 1
            occupied_live_mcp_names[r.project_id].add(name)

        conn.execute(
            sa.text(
                """
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, data, credential_type, mcp_server_url,
                     normalized_mcp_server_url, oauth_config, group_id, is_default,
                     archived_at, deleted_at, created_at, updated_at)
                VALUES
                    (:id, :project_id, 'mcp', :name, :data, :credential_type, :mcp_server_url,
                     :normalized, CAST(:oauth_config AS JSONB), :group_id, false,
                     :archived_at, :deleted_at, :created_at, :updated_at)
                """
            ),
            {
                "id": r.id,
                "project_id": r.project_id,
                "name": name,
                "data": json.dumps({"token_value": r.token_value}),
                "credential_type": r.credential_type,
                "mcp_server_url": r.mcp_server_url,
                "normalized": normalize_mcp_url(r.mcp_server_url),
                "oauth_config": json.dumps(r.oauth_config) if r.oauth_config is not None else None,
                "group_id": r.vault_id,
                "archived_at": r.archived_at,
                "deleted_at": r.deleted_at,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            },
        )

    # 3) secrets -> credentials(kind in {model, service}) ----------------------
    #    kind inference: referenced by any model consumer, marked default, or
    #    backed by a real provider => model, else service. Model consumers include
    #    active-session snapshots, not only the current agent row.
    model_references, _, _ = _collect_legacy_references(conn)
    model_reference_names = {
        (project_id, name) for _, _, project_id, name in model_references
    }

    secret_rows = conn.execute(
        sa.text(
            """
            SELECT id, project_id, name, provider, protocol, data, is_default,
                   deleted_at, created_at, updated_at
            FROM joysafeter_secrets
            ORDER BY project_id, name, created_at, id
            """
        )
    ).fetchall()

    # Latest non-deleted row per (project_id, name) keeps the canonical name — that
    # is what old name-based references resolved to (ORDER BY created_at DESC).
    latest_by_name: dict[tuple, str] = {}
    for r in secret_rows:
        if r.deleted_at is None:
            latest_by_name[(r.project_id, r.name)] = str(r.id)  # later rows overwrite -> latest wins

    for r in secret_rows:
        is_model = _secret_is_model(
            r.is_default, r.project_id, r.name, r.provider, model_reference_names
        )
        kind = "model" if is_model else "service"

        name = r.name
        if r.deleted_at is None and latest_by_name[(r.project_id, r.name)] != str(r.id):
            name = f"{r.name} (migrated-dup {r.id})"

        conn.execute(
            sa.text(
                """
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, data, provider, protocol, is_default,
                     deleted_at, created_at, updated_at)
                VALUES
                    (:id, :project_id, :kind, :name, :data, :provider, :protocol, :is_default,
                     :deleted_at, :created_at, :updated_at)
                """
            ),
            {
                "id": r.id,
                "project_id": r.project_id,
                "kind": kind,
                "name": name,
                "data": json.dumps(r.data) if not isinstance(r.data, str) else r.data,
                # service must have NULL provider/protocol per CHECK; model keeps them.
                "provider": r.provider if kind == "model" else None,
                "protocol": r.protocol if kind == "model" else None,
                "is_default": bool(r.is_default) if kind == "model" else False,
                "deleted_at": r.deleted_at,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            },
        )

    # 4) rewrite scalar references -------------------------------------------- #
    # agents.secret_ref (model name) -> agents.model_credential_id
    conn.execute(
        sa.text(
            """
            UPDATE joysafeter_agents a
            SET model_credential_id = c.id
            FROM joysafeter_credentials c
            WHERE c.kind = 'model' AND c.deleted_at IS NULL
              AND c.name = a.secret_ref
              AND c.project_id IS NOT DISTINCT FROM a.project_id
              AND a.secret_ref IS NOT NULL AND btrim(a.secret_ref) <> ''
            """
        )
    )

    # triggers.secret_ref (service name) + secret_key -> webhook_auth_* fields
    conn.execute(
        sa.text(
            """
            UPDATE joysafeter_triggers t
            SET webhook_auth_credential_id = c.id,
                webhook_auth_field = t.secret_key
            FROM joysafeter_credentials c
            WHERE c.kind = 'service' AND c.deleted_at IS NULL
              AND c.name = t.secret_ref
              AND c.project_id IS NOT DISTINCT FROM t.project_id
              AND t.secret_ref IS NOT NULL AND btrim(t.secret_ref) <> ''
            """
        )
    )

    # 5) sessions.vault_ids (uuid[] json) -> session_credential_groups rows ---- #
    #    group.id == vault.id, so vault ids map 1:1 to credential_group ids.
    conn.execute(
        sa.text(
            """
            INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
            SELECT s.id, (elem)::uuid
            FROM joysafeter_sessions s
            CROSS JOIN LATERAL jsonb_array_elements_text(s.vault_ids) AS elem
            WHERE s.vault_ids IS NOT NULL AND jsonb_typeof(s.vault_ids) = 'array'
              AND EXISTS (SELECT 1 FROM joysafeter_credential_groups g WHERE g.id = (elem)::uuid)
            ON CONFLICT DO NOTHING
            """
        )
    )

    # 6) environment.config JSON: names -> ids -------------------------------- #
    _rewrite_environment_config(conn)

    # 7) active-session agent_snapshot JSON: secret_ref -> model_credential_id - #
    _rewrite_session_snapshots(conn)


def _credential_id_for(conn, kind: str, project_id: Optional[str], name: str) -> Optional[str]:
    row = conn.execute(
        sa.text(
            "SELECT id FROM joysafeter_credentials WHERE kind=:kind AND deleted_at IS NULL "
            "AND name=:name AND project_id IS NOT DISTINCT FROM :pid "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {"kind": kind, "name": name, "pid": project_id},
    ).fetchone()
    return str(row[0]) if row else None


def _rewrite_environment_config(conn) -> None:
    rows = conn.execute(
        sa.text("SELECT id, project_id, config FROM joysafeter_environments WHERE config IS NOT NULL")
    ).fetchall()
    for r in rows:
        config = r.config if isinstance(r.config, dict) else json.loads(r.config or "{}")
        changed = False

        # secret_refs: list of service-credential NAMES -> list of ids
        refs = config.get("secret_refs")
        if isinstance(refs, list) and refs:
            new_refs = []
            for ref in refs:
                if isinstance(ref, str):
                    cid = _credential_id_for(conn, "service", r.project_id, ref)
                    new_refs.append(cid if cid else ref)
                    changed = changed or bool(cid)
                else:
                    new_refs.append(ref)
            config["secret_refs"] = new_refs

        # egress_services[].credential_ref (NAME) -> service_credential_id (id)
        services = config.get("egress_services")
        if isinstance(services, list):
            for svc in services:
                if isinstance(svc, dict) and svc.get("credential_ref") and "service_credential_id" not in svc:
                    cid = _credential_id_for(conn, "service", r.project_id, svc["credential_ref"])
                    if cid:
                        svc["service_credential_id"] = cid
                        svc.pop("credential_ref", None)
                        changed = True

        if changed:
            conn.execute(
                sa.text("UPDATE joysafeter_environments SET config = CAST(:cfg AS JSONB) WHERE id = :id"),
                {"cfg": json.dumps(config), "id": r.id},
            )


def _rewrite_session_snapshots(conn) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, project_id, agent_snapshot FROM joysafeter_sessions "
            "WHERE agent_snapshot IS NOT NULL"
        )
    ).fetchall()
    for r in rows:
        snap = r.agent_snapshot if isinstance(r.agent_snapshot, dict) else json.loads(r.agent_snapshot or "{}")
        secret_ref = snap.get("secret_ref")
        if isinstance(secret_ref, str) and secret_ref.strip():
            cid = _credential_id_for(conn, "model", r.project_id, secret_ref)
            if cid:
                snap["model_credential_id"] = cid
                snap.pop("secret_ref", None)
                conn.execute(
                    sa.text("UPDATE joysafeter_sessions SET agent_snapshot = CAST(:s AS JSONB) WHERE id = :id"),
                    {"s": json.dumps(snap), "id": r.id},
                )


# --------------------------------------------------------------------------- #
# teardown of legacy surface
# --------------------------------------------------------------------------- #
def _drop_legacy() -> None:
    op.drop_column("joysafeter_agents", "secret_ref")
    op.drop_column("joysafeter_triggers", "secret_ref")
    op.drop_column("joysafeter_triggers", "secret_key")
    op.drop_column("joysafeter_triggers", "system_prompt")
    op.drop_column("joysafeter_sessions", "vault_ids")
    op.drop_table("joysafeter_vault_credentials")
    op.drop_table("joysafeter_vaults")
    op.drop_table("joysafeter_secrets")


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Migration 20260814_000001 is online-only because it validates and rewrites live data."
        )
    conn = op.get_bind()
    _abort_on_null_project(conn)
    _abort_on_mcp_normalization_conflicts(conn)
    _abort_on_malformed_reference_json(conn)
    _abort_on_ambiguous_or_unresolved_references(conn)
    _abort_on_duplicate_default_model_protocol(conn)
    _abort_on_invalid_skill_usage_ids(conn)
    _rename_agent_mcp_configs()
    _align_skill_usage_id_types()
    _create_tables()
    _add_reference_columns()
    _backfill(conn)
    _add_foreign_keys()
    _drop_legacy()


def downgrade() -> None:
    # This is a data-consolidating migration; the legacy secrets/vaults rows are
    # merged and renamed, so a faithful reverse is not possible. Restore from a
    # pre-migration backup instead.
    raise NotImplementedError(
        "Downgrade of 20260814_000001_unify_credentials is not supported; "
        "restore the database from a backup taken before the upgrade."
    )
