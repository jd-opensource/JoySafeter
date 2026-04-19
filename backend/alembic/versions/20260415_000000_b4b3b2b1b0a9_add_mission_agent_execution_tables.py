"""add_mission_agent_execution_tables

Revision ID: b4b3b2b1b0a9
Revises: 0f7082711f20
Create Date: 2026-04-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4b3b2b1b0a9"
down_revision: Union[str, None] = "0f7082711f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE missionstatus AS ENUM ('backlog','todo','in_progress','in_review','done','blocked','cancelled');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE missionpriority AS ENUM ('none','low','medium','high','urgent');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE agentstatus AS ENUM ('idle','working','blocked','error','offline');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE missionexecutionstatus AS ENUM ('queued','dispatched','running','interrupt_wait','approval_wait','completed','failed','cancelled');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE executionsource AS ENUM ('mission','chat','graph','coordinator','api');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)

    # --- missions ---
    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "backlog",
                "todo",
                "in_progress",
                "in_review",
                "done",
                "blocked",
                "cancelled",
                name="missionstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="backlog",
        ),
        sa.Column(
            "priority",
            postgresql.ENUM("none", "low", "medium", "high", "urgent", name="missionpriority", create_type=False),
            nullable=False,
            server_default="none",
        ),
        sa.Column("assignee_type", sa.String(50), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("creator_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "parent_mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("missions_workspace_status_idx", "missions", ["workspace_id", "status"])
    op.create_index("missions_assignee_idx", "missions", ["assignee_type", "assignee_id"])
    op.create_index("missions_creator_idx", "missions", ["creator_id", "created_at"])

    # --- agent_profiles ---
    op.create_table(
        "agent_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("avatar", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("runtime_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("idle", "working", "blocked", "error", "offline", name="agentstatus", create_type=False),
            nullable=False,
            server_default="offline",
        ),
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("skill_ids", postgresql.JSONB(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("custom_env", postgresql.JSONB(), nullable=True),
        sa.Column("runtime_config", postgresql.JSONB(), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False, server_default="workspace"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("agent_profiles_workspace_idx", "agent_profiles", ["workspace_id"])
    op.create_index("agent_profiles_workspace_status_idx", "agent_profiles", ["workspace_id", "status"])

    # --- executions ---
    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(
                "mission", "chat", "graph", "coordinator", "api", name="executionsource", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "dispatched",
                "running",
                "interrupt_wait",
                "approval_wait",
                "completed",
                "failed",
                "cancelled",
                name="missionexecutionstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("runtime_type", sa.String(50), nullable=False),
        sa.Column("runtime_config", postgresql.JSONB(), nullable=True),
        sa.Column("container_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("prior_session_id", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("work_dir", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("executions_workspace_status_idx", "executions", ["workspace_id", "status"])
    op.create_index("executions_mission_idx", "executions", ["mission_id"])
    op.create_index("executions_agent_profile_idx", "executions", ["agent_profile_id"])
    op.create_index("executions_parent_idx", "executions", ["parent_execution_id"])
    op.create_index("executions_user_created_idx", "executions", ["user_id", "created_at"])

    # --- execution_events ---
    op.create_table(
        "execution_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_execution_events_exec_seq", "execution_events", ["execution_id", "seq"])
    op.create_index("execution_events_exec_created_idx", "execution_events", ["execution_id", "created_at"])

    # --- execution_snapshots ---
    op.create_table(
        "execution_snapshots",
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(100), nullable=False),
        sa.Column("projection", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("execution_snapshots")
    op.drop_table("execution_events")
    op.drop_table("executions")
    op.drop_table("agent_profiles")
    op.drop_table("missions")
    op.execute("DROP TYPE IF EXISTS executionsource")
    op.execute("DROP TYPE IF EXISTS missionexecutionstatus")
    op.execute("DROP TYPE IF EXISTS agentstatus")
    op.execute("DROP TYPE IF EXISTS missionpriority")
    op.execute("DROP TYPE IF EXISTS missionstatus")
