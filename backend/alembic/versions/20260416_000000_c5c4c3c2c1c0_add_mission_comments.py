"""add_mission_comments

Revision ID: c5c4c3c2c1c0
Revises: b4b3b2b1b0a9
Create Date: 2026-04-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5c4c3c2c1c0"
down_revision: Union[str, None] = "b4b3b2b1b0a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE commentauthortype AS ENUM ('member','agent');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE commenttype AS ENUM ('comment','status_change','progress_update','system');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)

    # --- mission_comments ---
    op.create_table(
        "mission_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_type", postgresql.ENUM("member", "agent", name="commentauthortype", create_type=False), nullable=False),
        sa.Column("author_id", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", postgresql.ENUM("comment", "status_change", "progress_update", "system", name="commenttype", create_type=False), nullable=False, server_default="comment"),
        sa.Column("parent_comment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mission_comments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("mission_comments_mission_created_idx", "mission_comments", ["mission_id", "created_at"])
    op.create_index("mission_comments_workspace_idx", "mission_comments", ["workspace_id"])
    op.create_index("mission_comments_author_idx", "mission_comments", ["author_type", "author_id"])
    op.create_index("mission_comments_parent_idx", "mission_comments", ["parent_comment_id"])

    # --- Add trigger_comment_id to executions ---
    op.add_column(
        "executions",
        sa.Column(
            "trigger_comment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mission_comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("executions_trigger_comment_idx", "executions", ["trigger_comment_id"])

    # --- Dedup guard: at most one pending execution per (mission, agent) ---
    op.execute("""
    CREATE UNIQUE INDEX uq_executions_mission_agent_pending
    ON executions (mission_id, agent_profile_id)
    WHERE status IN ('queued', 'dispatched');
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_executions_mission_agent_pending")
    op.drop_index("executions_trigger_comment_idx", table_name="executions")
    op.drop_column("executions", "trigger_comment_id")
    op.drop_table("mission_comments")
    op.execute("DROP TYPE IF EXISTS commenttype")
    op.execute("DROP TYPE IF EXISTS commentauthortype")
