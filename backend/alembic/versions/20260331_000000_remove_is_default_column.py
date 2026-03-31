"""Remove is_default column from model_instance table.

The default model mechanism is replaced by explicit model selection.

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-03-31 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t5u6v7w8x9y0"
down_revision: Union[str, None] = "s4t5u6v7w8x9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("model_instance", "is_default")


def downgrade() -> None:
    op.add_column(
        "model_instance",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
