"""Add durable residual sandbox cleanup work.

Revision ID: 20260901_000002
Revises: 20260901_000001
Create Date: 2026-09-01 00:00:02.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260901_000002"
down_revision: Union[str, None] = "20260901_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_sandbox_cleanup_work",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text(), nullable=False),
        sa.Column("resource_path", sa.Text(), nullable=False),
        sa.Column("node_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claim_owner", sa.Text(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed')",
            name="ck_sandbox_cleanup_work_status",
        ),
        sa.ForeignKeyConstraint(["sandbox_id"], ["joysafeter_sandboxes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sandbox_id",
            "resource_kind",
            "resource_name",
            name="uq_sandbox_cleanup_resource",
        ),
    )
    op.create_index(
        "idx_sandbox_cleanup_due",
        "joysafeter_sandbox_cleanup_work",
        ["provider", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("idx_sandbox_cleanup_due", table_name="joysafeter_sandbox_cleanup_work")
    op.drop_table("joysafeter_sandbox_cleanup_work")
