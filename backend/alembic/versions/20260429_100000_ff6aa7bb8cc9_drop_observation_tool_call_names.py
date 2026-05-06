"""drop dead tool_call_names column from observations

Revision ID: ff6aa7bb8cc9
Revises: ee5ff6aa7bb8
Create Date: 2026-04-29 10:00:00.000000+00:00

Changes:
- Drop tool_call_names column from observations table (never populated)
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "ff6aa7bb8cc9"
down_revision: Union[str, None] = "ee5ff6aa7bb8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("observations", "tool_call_names")


def downgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("tool_call_names", sa.ARRAY(sa.String), nullable=True),
    )
