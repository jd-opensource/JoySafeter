"""add processed_at to conductor_session_events

Revision ID: d1d2d3d4d5d6
Revises: c0c1c2c3c4c5
Create Date: 2026-05-19 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d1d2d3d4d5d6"
down_revision = "c0c1c2c3c4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conductor_session_events",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conductor_session_events", "processed_at")
