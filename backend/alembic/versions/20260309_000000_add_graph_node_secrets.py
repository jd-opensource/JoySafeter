"""add graph_node_secrets table for encrypted a2a_auth_headers

Revision ID: a1b2c3d4e5f6
Revises: 0faa0dc41210
Create Date: 2026-03-09 00:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "0faa0dc41210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_node_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_slug", sa.String(64), nullable=False, server_default="a2a_auth_headers"),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("graph_node_secrets_graph_node_idx", "graph_node_secrets", ["graph_id", "node_id"], unique=False)


def downgrade() -> None:
    op.drop_index("graph_node_secrets_graph_node_idx", table_name="graph_node_secrets")
    op.drop_table("graph_node_secrets")
