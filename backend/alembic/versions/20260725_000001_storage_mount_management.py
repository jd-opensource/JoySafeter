"""storage mount management

Revision ID: 20260725_000001
Revises: 20260727_000001
Create Date: 2026-07-25 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260725_000001"
down_revision: Union[str, None] = "20260727_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_storage_volumes",
        sa.Column("id", sa.UUID(), nullable=False),
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

    op.create_table(
        "joysafeter_storage_project_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", sa.UUID(), nullable=False),
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

    op.create_table(
        "joysafeter_session_storage_mounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("volume_id", sa.UUID(), nullable=False),
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
    op.create_index(
        "idx_joysafeter_session_storage_mounts_session", "joysafeter_session_storage_mounts", ["session_id"]
    )
    op.create_index("idx_joysafeter_session_storage_mounts_volume", "joysafeter_session_storage_mounts", ["volume_id"])
    op.create_index(
        "idx_joysafeter_session_storage_mounts_project", "joysafeter_session_storage_mounts", ["project_id"]
    )

    op.create_table(
        "joysafeter_storage_mount_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("environment_id", sa.UUID(), nullable=True),
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
    op.create_index(
        "idx_joysafeter_storage_audit_project_created", "joysafeter_storage_mount_audit", ["project_id", "created_at"]
    )
    op.create_index("idx_joysafeter_storage_audit_session", "joysafeter_storage_mount_audit", ["session_id"])
    op.create_index("idx_joysafeter_storage_audit_volume", "joysafeter_storage_mount_audit", ["volume_id"])
    op.create_index("idx_joysafeter_storage_audit_action", "joysafeter_storage_mount_audit", ["action"])


def downgrade() -> None:
    op.drop_index("idx_joysafeter_storage_audit_action", table_name="joysafeter_storage_mount_audit")
    op.drop_index("idx_joysafeter_storage_audit_volume", table_name="joysafeter_storage_mount_audit")
    op.drop_index("idx_joysafeter_storage_audit_session", table_name="joysafeter_storage_mount_audit")
    op.drop_index("idx_joysafeter_storage_audit_project_created", table_name="joysafeter_storage_mount_audit")
    op.drop_table("joysafeter_storage_mount_audit")
    op.drop_index("idx_joysafeter_session_storage_mounts_project", table_name="joysafeter_session_storage_mounts")
    op.drop_index("idx_joysafeter_session_storage_mounts_volume", table_name="joysafeter_session_storage_mounts")
    op.drop_index("idx_joysafeter_session_storage_mounts_session", table_name="joysafeter_session_storage_mounts")
    op.drop_table("joysafeter_session_storage_mounts")
    op.drop_index("idx_joysafeter_storage_grants_volume", table_name="joysafeter_storage_project_grants")
    op.drop_index("idx_joysafeter_storage_grants_project", table_name="joysafeter_storage_project_grants")
    op.drop_table("joysafeter_storage_project_grants")
    op.drop_index("idx_joysafeter_storage_volumes_enabled", table_name="joysafeter_storage_volumes")
    op.drop_index("uq_joysafeter_storage_volumes_ref_active", table_name="joysafeter_storage_volumes")
    op.drop_table("joysafeter_storage_volumes")
