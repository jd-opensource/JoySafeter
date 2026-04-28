"""add traces and observations tables"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "dd4ee5ff6aa7"
down_revision = "cc3dd4ee5ff6"


def upgrade():
    op.create_table(
        "traces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("environment", sa.String(50), server_default="debug"),
        sa.Column("tags", sa.ARRAY(sa.String), server_default="{}"),
        sa.Column("release", sa.String(255)),
        sa.Column("version", sa.String(100)),
        sa.Column("session_id", sa.String(255)),
        sa.Column("bookmarked", sa.Boolean, server_default="false"),
        sa.Column("public", sa.Boolean, server_default="false"),
        sa.Column("total_observations", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("total_cost", sa.Numeric(12, 6)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_traces_workspace_created", "traces", ["workspace_id", "created_at"])
    op.create_index("ix_traces_execution", "traces", ["execution_id"], unique=True)
    op.create_index("ix_traces_session", "traces", ["session_id", "created_at"])

    op.create_table(
        "observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("trace_id", UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_observation_id", UUID(as_uuid=True)),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default="DEFAULT"),
        sa.Column("status_message", sa.Text),
        sa.Column("environment", sa.String(50), server_default="debug"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("completion_start_time", sa.DateTime(timezone=True)),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("model", sa.String(100)),
        sa.Column("model_parameters", JSONB),
        sa.Column("usage_details", JSONB),
        sa.Column("cost_details", JSONB),
        sa.Column("prompt_name", sa.String(255)),
        sa.Column("prompt_version", sa.Integer),
        sa.Column("tool_definitions", JSONB),
        sa.Column("tool_calls", JSONB),
        sa.Column("tool_call_names", sa.ARRAY(sa.String)),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_observations_trace_time", "observations", ["trace_id", "start_time"])
    op.create_index("ix_observations_parent", "observations", ["parent_observation_id"])
    op.create_index("ix_observations_trace_type", "observations", ["trace_id", "type"])


def downgrade():
    op.drop_table("observations")
    op.drop_table("traces")
