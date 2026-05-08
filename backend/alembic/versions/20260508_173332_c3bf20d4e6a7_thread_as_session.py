"""thread_as_session

Revision ID: c3bf20d4e6a7
Revises: b2af1f3e0215
Create Date: 2026-05-08

Establish Thread as the session root:
- threads gains container_id, cli_session_id, last_active_at (pool persistence)
- agent_runs.thread_id is now NOT NULL (every run belongs to a thread)
- tasks gains thread_id NOT NULL (every task owns a thread)
- Rows without thread_id are deleted (greenfield, no back-fill)
"""

from alembic import op
import sqlalchemy as sa


revision = "c3bf20d4e6a7"
down_revision = "b2af1f3e0215"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Drop orphan agent_runs (no thread). Greenfield cleanup before NOT NULL.
    op.execute("DELETE FROM agent_runs WHERE thread_id IS NULL")

    # 2. threads: add pool persistence columns
    op.add_column("threads", sa.Column("container_id", sa.String(length=128), nullable=True))
    op.add_column("threads", sa.Column("cli_session_id", sa.String(length=255), nullable=True))
    op.add_column(
        "threads",
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_threads_lru",
        "threads",
        [sa.text("last_active_at DESC")],
        postgresql_where=sa.text("status = 'active'"),
    )

    # 3. agent_runs.thread_id NOT NULL
    op.alter_column(
        "agent_runs",
        "thread_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    # 4. tasks.thread_id — added nullable in this PR; full Task↔Thread
    #    binding (NOT NULL + auto-provision on task create) lands in PR3.
    op.add_column(
        "tasks",
        sa.Column("thread_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_thread_id_threads",
        "tasks",
        "threads",
        ["thread_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_tasks_thread_id_threads", "tasks", type_="foreignkey")
    op.drop_column("tasks", "thread_id")

    op.alter_column("agent_runs", "thread_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)

    op.drop_index("idx_threads_lru", table_name="threads")
    op.drop_column("threads", "last_active_at")
    op.drop_column("threads", "cli_session_id")
    op.drop_column("threads", "container_id")
