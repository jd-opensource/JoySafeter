"""drop_openclaw_task_table

Revision ID: 000000000010
Revises: 000000000009
Create Date: 2026-02-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "000000000010"
down_revision: Union[str, None] = "000000000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("openclaw_task")


def downgrade() -> None:
    op.create_table(
        "openclaw_task",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(["instance_id"], ["openclaw_instance.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_openclaw_task_user_id", "openclaw_task", ["user_id"])
    op.create_index("ix_openclaw_task_status", "openclaw_task", ["status"])
    op.create_index("ix_openclaw_task_instance_id", "openclaw_task", ["instance_id"])
