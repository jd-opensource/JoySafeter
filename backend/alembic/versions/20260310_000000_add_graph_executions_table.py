"""add graph_executions table for OpenAPI graph run/status/abort/result

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-10 20:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(255),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_key.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("init", "executing", "finish", "failed", name="executionstatus"),
            nullable=False,
            server_default="init",
        ),
        sa.Column("input_variables", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("graph_executions_graph_id_idx", "graph_executions", ["graph_id"], unique=False)
    op.create_index("graph_executions_user_id_idx", "graph_executions", ["user_id"], unique=False)
    op.create_index("graph_executions_status_idx", "graph_executions", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("graph_executions_status_idx", table_name="graph_executions")
    op.drop_index("graph_executions_user_id_idx", table_name="graph_executions")
    op.drop_index("graph_executions_graph_id_idx", table_name="graph_executions")
    op.drop_table("graph_executions")
    op.execute("DROP TYPE IF EXISTS executionstatus")
