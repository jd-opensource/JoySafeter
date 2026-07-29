"""add project-level trigger pause kill switch

Revision ID: 20260728_000001
Revises: 20260727_000004
Create Date: 2026-07-28 11:20:00.000000
"""

from __future__ import annotations

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_000001"
down_revision: Union[str, None] = "20260727_000004"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_organization_projects",
        sa.Column(
            "triggers_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("joysafeter_organization_projects", "triggers_paused")
