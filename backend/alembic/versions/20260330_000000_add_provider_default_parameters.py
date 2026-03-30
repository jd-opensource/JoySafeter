"""add default_parameters to model_provider

Revision ID: p1q2r3s4t5u6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_provider",
        sa.Column("default_parameters", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("model_provider", "default_parameters")
