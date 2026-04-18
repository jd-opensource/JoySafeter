"""add_mission_auto_approve

Revision ID: e7e6e5e4e3e2
Revises: d6d5d4d3d2d1
Create Date: 2026-04-18 00:00:01.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7e6e5e4e3e2"
down_revision: Union[str, None] = "d6d5d4d3d2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("missions", "auto_approve")
