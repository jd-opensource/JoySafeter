"""refactor_openclaw_worker_to_instance

Revision ID: 000000000009
Revises: 000000000008
Create Date: 2026-02-26 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "000000000009"
down_revision: Union[str, None] = "000000000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old FK and indexes on openclaw_task that reference openclaw_worker
    op.drop_index("ix_openclaw_task_worker_id", table_name="openclaw_task")
    op.drop_constraint("fk_openclaw_task_worker_id_openclaw_worker", "openclaw_task", type_="foreignkey")
    op.drop_column("openclaw_task", "worker_id")

    # Drop old openclaw_worker table
    op.drop_table("openclaw_worker")

    # Create new openclaw_instance table
    op.create_table(
        "openclaw_instance",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("container_id", sa.String(length=255), nullable=True),
        sa.Column("gateway_port", sa.Integer(), nullable=False),
        sa.Column("gateway_token", sa.String(length=512), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_openclaw_instance_user_id", "openclaw_instance", ["user_id"])

    # Add instance_id column to openclaw_task
    op.add_column("openclaw_task", sa.Column("instance_id", sa.String(length=255), nullable=True))
    op.create_foreign_key(
        "fk_openclaw_task_instance_id_openclaw_instance",
        "openclaw_task",
        "openclaw_instance",
        ["instance_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_openclaw_task_instance_id", "openclaw_task", ["instance_id"])


def downgrade() -> None:
    # Remove instance_id from openclaw_task
    op.drop_index("ix_openclaw_task_instance_id", table_name="openclaw_task")
    op.drop_constraint("fk_openclaw_task_instance_id_openclaw_instance", "openclaw_task", type_="foreignkey")
    op.drop_column("openclaw_task", "instance_id")

    # Drop openclaw_instance table
    op.drop_index("ix_openclaw_instance_user_id", table_name="openclaw_instance")
    op.drop_table("openclaw_instance")

    # Recreate openclaw_worker table
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

    # Restore worker_id column on openclaw_task
    op.add_column("openclaw_task", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.create_foreign_key(
        "fk_openclaw_task_worker_id_openclaw_worker",
        "openclaw_task",
        "openclaw_worker",
        ["worker_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_openclaw_task_worker_id", "openclaw_task", ["worker_id"])
