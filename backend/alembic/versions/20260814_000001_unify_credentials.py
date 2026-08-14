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
* kind inference for a secret: 'model' if it is referenced by an agent's model
  slot OR its provider is a real provider (not the 'custom' default); otherwise
  'service'. Service credentials must have NULL provider/protocol (CHECK), so we
  clear those two columns for them.
* duplicate (project_id, name): the legacy schema allowed duplicate secret names
  (resolution was "latest created_at wins"). The new partial unique index
  forbids duplicates among non-deleted rows, so older same-name rows are kept
  (no data loss) but their name is suffixed "(migrated-dup <shortid>)". The
  latest row keeps the original name and is what references resolve to.
"""

from __future__ import annotations

import json
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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
def _abort_on_null_project(conn) -> None:
    problems = {}
    for table in ("joysafeter_secrets", "joysafeter_vaults"):
        rows = conn.execute(
            sa.text(f"SELECT id FROM {table} WHERE project_id IS NULL AND deleted_at IS NULL")
        ).fetchall()
        if rows:
            problems[table] = [str(r[0]) for r in rows]
    if problems:
        raise RuntimeError(
            "Cannot migrate: the new credential tables require project_id NOT NULL, "
            "but these live rows have a NULL project_id. Assign a project to them "
            f"(or soft-delete them) and re-run. Offending rows: {problems}"
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
            """
        )
    ).fetchall()
    for r in vc_rows:
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
                "name": r.name,
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
    #    kind inference: referenced-by-agent OR real provider => model, else service.
    agent_model_names = {
        (row.project_id, row.secret_ref)
        for row in conn.execute(
            sa.text(
                "SELECT project_id, secret_ref FROM joysafeter_agents "
                "WHERE secret_ref IS NOT NULL AND btrim(secret_ref) <> ''"
            )
        ).fetchall()
    }

    secret_rows = conn.execute(
        sa.text(
            """
            SELECT id, project_id, name, provider, protocol, data, is_default,
                   deleted_at, created_at, updated_at
            FROM joysafeter_secrets
            ORDER BY project_id, name, created_at
            """
        )
    ).fetchall()

    # Track (project_id, kind, name) already used by a *non-deleted* row so we can
    # suffix later duplicates instead of violating uq_credentials_project_kind_name.
    used_names: set[tuple] = set()
    # Latest non-deleted row per (project_id, name) keeps the canonical name — that
    # is what old name-based references resolved to (ORDER BY created_at DESC).
    latest_by_name: dict[tuple, str] = {}
    for r in secret_rows:
        if r.deleted_at is None:
            latest_by_name[(r.project_id, r.name)] = str(r.id)  # later rows overwrite -> latest wins

    for r in secret_rows:
        is_model = (r.project_id, r.name) in agent_model_names or (
            r.provider is not None and r.provider not in ("custom", "")
        )
        kind = "model" if is_model else "service"

        name = r.name
        if r.deleted_at is None:
            key = (r.project_id, kind, name)
            if key in used_names:
                name = f"{r.name} (migrated-dup {str(r.id)[:8]})"
            used_names.add((r.project_id, kind, name))

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


def _model_id_for(conn, project_id: Optional[str], name: str) -> Optional[str]:
    row = conn.execute(
        sa.text(
            "SELECT id FROM joysafeter_credentials WHERE kind='model' AND deleted_at IS NULL "
            "AND name=:name AND project_id IS NOT DISTINCT FROM :pid "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"name": name, "pid": project_id},
    ).fetchone()
    return str(row[0]) if row else None


def _service_id_for(conn, project_id: Optional[str], name: str) -> Optional[str]:
    row = conn.execute(
        sa.text(
            "SELECT id FROM joysafeter_credentials WHERE kind='service' AND deleted_at IS NULL "
            "AND name=:name AND project_id IS NOT DISTINCT FROM :pid "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"name": name, "pid": project_id},
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
                    cid = _service_id_for(conn, r.project_id, ref)
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
                    cid = _service_id_for(conn, r.project_id, svc["credential_ref"])
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
            cid = _model_id_for(conn, r.project_id, secret_ref)
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
    op.drop_column("joysafeter_sessions", "vault_ids")
    op.drop_table("joysafeter_vault_credentials")
    op.drop_table("joysafeter_vaults")
    op.drop_table("joysafeter_secrets")


def upgrade() -> None:
    conn = op.get_bind()
    _abort_on_null_project(conn)
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
