"""add session stats columns to conductor_sessions

Revision ID: g1g2g3g4g5g6
Revises: f1f2f3f4f5f6
Create Date: 2026-05-20 00:00:02.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "g1g2g3g4g5g6"
down_revision = "f1f2f3f4f5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conductor_sessions",
        sa.Column("active_seconds", sa.Float(), nullable=True),
    )
    op.add_column(
        "conductor_sessions",
        sa.Column("duration_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conductor_sessions", "duration_seconds")
    op.drop_column("conductor_sessions", "active_seconds")
