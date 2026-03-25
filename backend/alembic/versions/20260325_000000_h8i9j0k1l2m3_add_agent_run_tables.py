"""add agent run persistence tables

Revision ID: h8i9j0k1l2m3
Revises: g7a8b9c0d1e2
Create Date: 2026-03-25 12:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(length=255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "graph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graphs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("thread_id", sa.String(length=100), nullable=True),
        sa.Column("run_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "interrupt_wait",
                "completed",
                "failed",
                "cancelled",
                name="agentrunstatus",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("agent_runs_user_created_idx", "agent_runs", ["user_id", "created_at"], unique=False)
    op.create_index("agent_runs_thread_created_idx", "agent_runs", ["thread_id", "created_at"], unique=False)
    op.create_index("agent_runs_graph_created_idx", "agent_runs", ["graph_id", "created_at"], unique=False)
    op.create_index("agent_runs_status_updated_idx", "agent_runs", ["status", "updated_at"], unique=False)

    op.create_table(
        "agent_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_run_events_run_seq"),
    )
    op.create_index("agent_run_events_run_seq_idx", "agent_run_events", ["run_id", "seq"], unique=False)
    op.create_index("agent_run_events_run_created_idx", "agent_run_events", ["run_id", "created_at"], unique=False)

    op.create_table(
        "agent_run_snapshots",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("projection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("agent_run_snapshots")
    op.drop_index("agent_run_events_run_created_idx", table_name="agent_run_events")
    op.drop_index("agent_run_events_run_seq_idx", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_index("agent_runs_status_updated_idx", table_name="agent_runs")
    op.drop_index("agent_runs_graph_created_idx", table_name="agent_runs")
    op.drop_index("agent_runs_thread_created_idx", table_name="agent_runs")
    op.drop_index("agent_runs_user_created_idx", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.execute("DROP TYPE IF EXISTS agentrunstatus")
