"""repair storage mount tables for already-stamped databases

Revision ID: 20260728_000002
Revises: 20260728_000001
Create Date: 2026-07-28 20:35:00.000000

Some local/long-lived databases had already advanced past 20260728_000001
before the storage migrations were inserted into the middle of the revision
chain. Alembic correctly reports those databases at head, but the actual
storage tables are absent. This forward-only repair migration makes the schema
match the current model state without disturbing databases that already ran the
storage migrations through the normal path.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260728_000002"
down_revision: Union[str, None] = "20260728_000001"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def _has_table(table_name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _create_storage_volumes() -> None:
    op.create_table(
        "joysafeter_storage_volumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_ref", sa.String(length=128), nullable=False),
        sa.Column("backend_type", sa.String(length=32), server_default="generic", nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("max_access", sa.String(length=16), server_default="read_only", nullable=False),
        sa.Column("allowed_prefixes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("docker", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("k8s", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=True),
        sa.Column("used_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_joysafeter_storage_volumes_ref_active",
        "joysafeter_storage_volumes",
        ["volume_ref"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("idx_joysafeter_storage_volumes_enabled", "joysafeter_storage_volumes", ["enabled"])


def _create_storage_project_grants() -> None:
    op.create_table(
        "joysafeter_storage_project_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("max_access", sa.String(length=16), server_default="read_only", nullable=False),
        sa.Column("allowed_prefixes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["joysafeter_organization_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["volume_id"], ["joysafeter_storage_volumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("volume_id", "project_id", name="uq_joysafeter_storage_grants_volume_project"),
    )
    op.create_index("idx_joysafeter_storage_grants_project", "joysafeter_storage_project_grants", ["project_id"])
    op.create_index("idx_joysafeter_storage_grants_volume", "joysafeter_storage_project_grants", ["volume_id"])


def _create_session_storage_mounts() -> None:
    op.create_table(
        "joysafeter_session_storage_mounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("sub_path", sa.Text(), server_default="", nullable=False),
        sa.Column("mount_path", sa.Text(), nullable=False),
        sa.Column("access", sa.String(length=16), server_default="read_only", nullable=False),
        sa.Column("required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["joysafeter_organization_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["joysafeter_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["volume_id"], ["joysafeter_storage_volumes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "mount_path", name="uq_joysafeter_session_storage_mount_path"),
    )
    op.create_index("idx_joysafeter_session_storage_mounts_session", "joysafeter_session_storage_mounts", ["session_id"])
    op.create_index("idx_joysafeter_session_storage_mounts_volume", "joysafeter_session_storage_mounts", ["volume_id"])
    op.create_index("idx_joysafeter_session_storage_mounts_project", "joysafeter_session_storage_mounts", ["project_id"])


def _create_storage_mount_audit() -> None:
    op.create_table(
        "joysafeter_storage_mount_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("volume_ref", sa.String(length=128), nullable=True),
        sa.Column("mount_path", sa.Text(), nullable=True),
        sa.Column("sub_path", sa.Text(), nullable=True),
        sa.Column("access", sa.String(length=16), nullable=True),
        sa.Column("bytes_used", sa.BigInteger(), nullable=True),
        sa.Column("result", sa.String(length=32), server_default="success", nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["volume_id"], ["joysafeter_storage_volumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_joysafeter_storage_audit_project_created", "joysafeter_storage_mount_audit", ["project_id", "created_at"])
    op.create_index("idx_joysafeter_storage_audit_session", "joysafeter_storage_mount_audit", ["session_id"])
    op.create_index("idx_joysafeter_storage_audit_volume", "joysafeter_storage_mount_audit", ["volume_id"])
    op.create_index("idx_joysafeter_storage_audit_action", "joysafeter_storage_mount_audit", ["action"])


def _create_storage_organization_grants() -> None:
    op.create_table(
        "joysafeter_storage_organization_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", sa.String(length=255), nullable=False),
        sa.Column("max_access", sa.String(length=16), server_default="read_only", nullable=False),
        sa.Column("allowed_prefixes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["joysafeter_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["volume_id"], ["joysafeter_storage_volumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("volume_id", "org_id", name="uq_joysafeter_storage_org_grants_volume_org"),
    )
    op.create_index("idx_joysafeter_storage_org_grants_org", "joysafeter_storage_organization_grants", ["org_id"])
    op.create_index("idx_joysafeter_storage_org_grants_volume", "joysafeter_storage_organization_grants", ["volume_id"])


def upgrade() -> None:
    if not _has_table("joysafeter_storage_volumes"):
        _create_storage_volumes()
    if not _has_table("joysafeter_storage_project_grants"):
        _create_storage_project_grants()
    if not _has_table("joysafeter_session_storage_mounts"):
        _create_session_storage_mounts()
    if not _has_table("joysafeter_storage_mount_audit"):
        _create_storage_mount_audit()
    if not _has_table("joysafeter_storage_organization_grants"):
        _create_storage_organization_grants()
        op.execute(
            """
            INSERT INTO joysafeter_storage_organization_grants (
                id, created_at, updated_at, volume_id, org_id, max_access, allowed_prefixes, quota_bytes, enabled
            )
            SELECT gen_random_uuid(), now(), now(), g.volume_id, p.org_id,
                   CASE WHEN bool_and(g.max_access = 'read_only') THEN 'read_only' ELSE 'read_write' END,
                   '[]'::jsonb,
                   MIN(g.quota_bytes),
                   true
              FROM joysafeter_storage_project_grants g
              JOIN joysafeter_organization_projects p ON p.id = g.project_id
          GROUP BY g.volume_id, p.org_id
            ON CONFLICT (volume_id, org_id) DO NOTHING
            """
        )


def downgrade() -> None:
    # Forward-only repair migration. The original storage migrations own these
    # tables in normal downgrade flows; dropping them here would destroy storage
    # data on databases that already had the tables.
    pass
