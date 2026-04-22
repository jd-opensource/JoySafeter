"""create new execution chain tables"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "dd44ee55ff66"
down_revision = "cc33dd44ee55"


def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("agent_releases.id"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("threads.id"), nullable=True),
        sa.Column("mission_id", UUID(as_uuid=True), sa.ForeignKey("missions.id"), nullable=True),
        sa.Column("trigger_source", sa.String(20), nullable=False),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("input_payload", JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("current_execution_id", UUID(as_uuid=True), nullable=True),  # FK added after executions
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "executions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("parent_execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("attempt_index", sa.Integer, nullable=False, server_default="1"),
        sa.Column("executor_kind", sa.String(20), nullable=False),
        sa.Column("runtime_session_ref", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("run_id", "attempt_index", name="uq_executions_run_attempt"),
    )

    # Circular FK: agent_runs.current_execution_id -> executions.id
    op.create_foreign_key(
        "fk_agent_runs_current_execution",
        "agent_runs", "executions",
        ["current_execution_id"], ["id"],
    )

    op.create_table(
        "execution_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("execution_id", "sequence_no", name="uq_execution_events_seq"),
    )


def downgrade():
    op.drop_table("execution_events")
    op.drop_constraint("fk_agent_runs_current_execution", "agent_runs", type_="foreignkey")
    op.drop_table("executions")
    op.drop_table("agent_runs")
