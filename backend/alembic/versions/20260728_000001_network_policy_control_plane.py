"""productionize sandbox network policy control plane

Revision ID: 20260728_000001
Revises: 20260727_000003
Create Date: 2026-07-28 15:30:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260728_000001"
down_revision: Union[str, Sequence[str], None] = "20260727_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_tasks",
        sa.Column("schedule_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "joysafeter_tasks",
        sa.Column("next_schedule_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_tasks",
        sa.Column("last_schedule_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_tasks",
        sa.Column("last_schedule_error_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_tasks",
        sa.Column("scheduling_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_joysafeter_tasks_pending_schedule_at",
        "joysafeter_tasks",
        ["next_schedule_at", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_status", sa.Text(), nullable=False, server_default="disabled"),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_policy_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_policy_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_joysafeter_sandboxes_networking_status",
        "joysafeter_sandboxes",
        ["networking_status"],
    )

    op.create_table(
        "joysafeter_sandbox_network_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.BigInteger(), nullable=False),
        sa.Column("desired_policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rendered_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_nack_reason", sa.Text(), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sandbox_id"], ["joysafeter_sandboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["joysafeter_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["joysafeter_tasks.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("sandbox_id", "policy_version", name="uq_jsnp_sandbox_policy_version"),
    )
    op.create_index(
        "idx_jsnp_sandbox_status",
        "joysafeter_sandbox_network_policies",
        ["sandbox_id", "status"],
    )
    op.create_index(
        "idx_jsnp_policy_hash",
        "joysafeter_sandbox_network_policies",
        ["policy_hash"],
    )
    op.create_index(
        "idx_jsnp_status_updated_at",
        "joysafeter_sandbox_network_policies",
        ["status", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_jsnp_policy_hash", table_name="joysafeter_sandbox_network_policies")
    op.drop_index("idx_jsnp_status_updated_at", table_name="joysafeter_sandbox_network_policies")
    op.drop_index("idx_jsnp_sandbox_status", table_name="joysafeter_sandbox_network_policies")
    op.drop_table("joysafeter_sandbox_network_policies")

    op.drop_index("idx_joysafeter_sandboxes_networking_status", table_name="joysafeter_sandboxes")
    op.drop_column("joysafeter_sandboxes", "networking_ready_at")
    op.drop_column("joysafeter_sandboxes", "networking_last_error")
    op.drop_column("joysafeter_sandboxes", "networking_policy_version")
    op.drop_column("joysafeter_sandboxes", "networking_policy_hash")
    op.drop_column("joysafeter_sandboxes", "networking_status")

    op.drop_index("idx_joysafeter_tasks_pending_schedule_at", table_name="joysafeter_tasks")
    op.drop_column("joysafeter_tasks", "scheduling_started_at")
    op.drop_column("joysafeter_tasks", "last_schedule_error_type")
    op.drop_column("joysafeter_tasks", "last_schedule_error")
    op.drop_column("joysafeter_tasks", "next_schedule_at")
    op.drop_column("joysafeter_tasks", "schedule_attempts")
