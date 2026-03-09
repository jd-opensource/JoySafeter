"""drop graph_nodes redundant columns; add graphs.deleted_at for soft delete

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-09 00:00:01.000000+00:00

- Drop graph_nodes.prompt, tools, memory (compiler uses data.config only).
- Add graphs.deleted_at for AgentGraph soft delete.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("graphs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("graph_nodes", "prompt")
    op.drop_column("graph_nodes", "tools")
    op.drop_column("graph_nodes", "memory")


def downgrade() -> None:
    op.drop_column("graphs", "deleted_at")
    op.add_column("graph_nodes", sa.Column("prompt", sa.Text(), nullable=True, server_default=""))
    op.add_column("graph_nodes", sa.Column("tools", postgresql.JSONB(), nullable=True, server_default="{}"))
    op.add_column("graph_nodes", sa.Column("memory", postgresql.JSONB(), nullable=True, server_default="{}"))
