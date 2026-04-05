"""Drop graph_test_cases table.

Feature removed — will be redesigned later.

Revision ID: a1b2c3d4e5f6
Revises: t5u6v7w8x9y0
Create Date: 2026-04-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "t5u6v7w8x9y0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("graph_test_cases")


def downgrade() -> None:
    op.create_table(
        "graph_test_cases",
        sa.Column("graph_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assertions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_id"], ["graphs.id"], name=op.f("fk_graph_test_cases_graph_id_graphs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_test_cases")),
    )
