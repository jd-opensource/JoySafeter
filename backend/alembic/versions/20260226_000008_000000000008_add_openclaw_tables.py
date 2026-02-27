"""add_openclaw_tables

Revision ID: 000000000008
Revises: 000000000007
Create Date: 2026-02-26 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000008"
down_revision: Union[str, None] = "000000000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openclaw_worker",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint_url", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("container_id", sa.String(length=255), nullable=True),
        sa.Column("current_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_tasks", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_url"),
    )

    op.create_table(
        "openclaw_task",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("redis_channel", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["openclaw_worker.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_openclaw_task_user_id", "openclaw_task", ["user_id"])
    op.create_index("ix_openclaw_task_worker_id", "openclaw_task", ["worker_id"])
    op.create_index("ix_openclaw_task_status", "openclaw_task", ["status"])


def downgrade() -> None:
    op.drop_index("ix_openclaw_task_status", table_name="openclaw_task")
    op.drop_index("ix_openclaw_task_worker_id", table_name="openclaw_task")
    op.drop_index("ix_openclaw_task_user_id", table_name="openclaw_task")
    op.drop_table("openclaw_task")
    op.drop_table("openclaw_worker")
