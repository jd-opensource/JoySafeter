"""tasks_require_agent_and_thread

Revision ID: d4c031e5f7b8
Revises: c3bf20d4e6a7
Create Date: 2026-05-08

Finishes Task↔Thread binding: every Task has an agent and a thread.
Tasks without an agent or without a thread are deleted (greenfield — callers
now create the Thread synchronously during task creation).
"""

import sqlalchemy as sa

from alembic import op

revision = "d4c031e5f7b8"
down_revision = "c3bf20d4e6a7"
branch_labels = None
depends_on = None


def upgrade():
    # Drop rows that cannot satisfy the new invariants (no agent or no thread).
    op.execute("DELETE FROM tasks WHERE agent_id IS NULL OR thread_id IS NULL")

    op.alter_column(
        "tasks",
        "agent_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "tasks",
        "thread_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "tasks",
        "thread_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "tasks",
        "agent_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
