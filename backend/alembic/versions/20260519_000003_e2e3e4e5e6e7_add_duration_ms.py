"""add duration_ms to conductor_tasks

Revision ID: e2e3e4e5e6e7
Revises: d1d2d3d4d5d6
Create Date: 2026-05-19 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e2e3e4e5e6e7"
down_revision = "d1d2d3d4d5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conductor_tasks",
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conductor_tasks", "duration_ms")
