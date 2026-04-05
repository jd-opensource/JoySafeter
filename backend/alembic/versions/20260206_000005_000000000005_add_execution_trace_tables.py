"""add_execution_trace_tables

Revision ID: 000000000005
Revises: 000000000004
Create Date: 2026-02-06 00:00:00.000000+00:00

Add execution trace table (execution_traces) and execution observation table (execution_observations)
for persisting LangGraph execution data, with support for hierarchical observation nesting.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000005"
down_revision: Union[str, None] = "000000000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============ execution_traces ============
    op.create_table(
        "execution_traces",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("graph_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.String(100), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", name="tracestatus"),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column("input", postgresql.JSON(), nullable=True),
        sa.Column("output", postgresql.JSON(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
        sa.Column("tags", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_execution_traces_workspace_id", "execution_traces", ["workspace_id"])
    op.create_index("ix_execution_traces_graph_id", "execution_traces", ["graph_id"])
    op.create_index("ix_execution_traces_thread_id", "execution_traces", ["thread_id"])
    op.create_index("ix_execution_traces_user_id", "execution_traces", ["user_id"])
    op.create_index("ix_execution_traces_graph_thread", "execution_traces", ["graph_id", "thread_id"])
    op.create_index("ix_execution_traces_start_time", "execution_traces", ["start_time"])

    # ============ execution_observations ============
    op.create_table(
        "execution_observations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "trace_id",
            sa.UUID(),
            sa.ForeignKey("execution_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_observation_id",
            sa.UUID(),
            sa.ForeignKey("execution_observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "type",
            sa.Enum("SPAN", "GENERATION", "TOOL", "EVENT", name="observationtype"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "level",
            sa.Enum("DEBUG", "DEFAULT", "WARNING", "ERROR", name="observationlevel"),
            nullable=False,
            server_default="DEFAULT",
        ),
        sa.Column(
            "status",
            sa.Enum("RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", name="observationstatus"),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("completion_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input", postgresql.JSON(), nullable=True),
        sa.Column("output", postgresql.JSON(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("model_provider", sa.String(100), nullable=True),
        sa.Column("model_parameters", postgresql.JSON(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("input_cost", sa.Float(), nullable=True),
        sa.Column("output_cost", sa.Float(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_execution_observations_trace_id", "execution_observations", ["trace_id"])
    op.create_index(
        "ix_execution_observations_parent_observation_id", "execution_observations", ["parent_observation_id"]
    )
    op.create_index("ix_execution_observations_trace_start", "execution_observations", ["trace_id", "start_time"])
    op.create_index("ix_execution_observations_type", "execution_observations", ["type"])


def downgrade() -> None:
    op.drop_table("execution_observations")
    op.drop_table("execution_traces")
    op.execute("DROP TYPE IF EXISTS observationstatus")
    op.execute("DROP TYPE IF EXISTS observationlevel")
    op.execute("DROP TYPE IF EXISTS observationtype")
    op.execute("DROP TYPE IF EXISTS tracestatus")
