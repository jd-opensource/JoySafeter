"""add agents and commands columns to conductor_agents

Revision ID: f1f2f3f4f5f6
Revises: e2e3e4e5e6e7
Create Date: 2026-05-20 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f1f2f3f4f5f6"
down_revision = "e2e3e4e5e6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conductor_agents",
        sa.Column("agents", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "conductor_agents",
        sa.Column("commands", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("conductor_agents", "commands")
    op.drop_column("conductor_agents", "agents")
