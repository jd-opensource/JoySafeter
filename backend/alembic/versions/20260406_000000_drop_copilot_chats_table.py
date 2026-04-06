"""Drop copilot_chats table.

Copilot conversation history is now stored in agent_runs / agent_run_events /
agent_run_snapshots.  The copilot_chats table, its model, and its repository are
no longer used.

Revision ID: 4a6b5e9517ae
Revises: 87be2dfd4240
Create Date: 2026-04-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a6b5e9517ae"
down_revision: Union[str, None] = "87be2dfd4240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("copilot_chats_agent_graph_id_idx", table_name="copilot_chats")
    op.drop_index("copilot_chats_user_id_idx", table_name="copilot_chats")
    op.drop_index("copilot_chats_created_at_idx", table_name="copilot_chats")
    op.drop_index("copilot_chats_updated_at_idx", table_name="copilot_chats")
    op.drop_table("copilot_chats")


def downgrade() -> None:
    op.create_table(
        "copilot_chats",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("agent_graph_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "model",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'claude-3-7-sonnet-latest'"),
        ),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("preview_yaml", sa.Text(), nullable=True),
        sa.Column("plan_artifact", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_copilot_chats_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_copilot_chats")),
    )
    op.create_index("copilot_chats_user_id_idx", "copilot_chats", ["user_id"])
    op.create_index("copilot_chats_agent_graph_id_idx", "copilot_chats", ["agent_graph_id"])
    op.create_index("copilot_chats_created_at_idx", "copilot_chats", ["created_at"])
    op.create_index("copilot_chats_updated_at_idx", "copilot_chats", ["updated_at"])
