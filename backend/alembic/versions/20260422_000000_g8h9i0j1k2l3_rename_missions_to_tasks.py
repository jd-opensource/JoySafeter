"""rename missions to tasks"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "g8h9i0j1k2l3"
down_revision = "z1a2b3c4d5e6"


def upgrade():
    # Rename table
    op.rename_table("missions", "tasks")

    # Rename columns
    op.alter_column("tasks", "assignee_id", new_column_name="agent_id")
    op.alter_column("tasks", "objective", new_column_name="goal")
    op.alter_column("tasks", "parent_mission_id", new_column_name="parent_task_id")

    # Drop assignee_type column (tasks always belong to agents)
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS assignee_type")

    # Drop current_execution_id (replaced by latest_run_id)
    # May already be dropped by a prior migration (_000007).
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS current_execution_id")

    # Add latest_run_id column
    op.add_column("tasks", sa.Column("latest_run_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_tasks_latest_run", "tasks", "agent_runs", ["latest_run_id"], ["id"])

    # Add FK from agent_id to agents table
    # Clean up orphaned references first (old assignee_id values from agent_profiles)
    op.execute("""
        UPDATE tasks SET agent_id = NULL
        WHERE agent_id IS NOT NULL
          AND agent_id NOT IN (SELECT id FROM agents)
    """)
    op.create_foreign_key("fk_tasks_agent", "tasks", "agents", ["agent_id"], ["id"])

    # Add FK from parent_task_id to tasks table
    op.create_foreign_key("fk_tasks_parent", "tasks", "tasks", ["parent_task_id"], ["id"], ondelete="SET NULL")

    # Update agent_runs table: rename mission_id FK reference
    op.alter_column("agent_runs", "mission_id", new_column_name="task_id")

    # Update indexes — use SQL-level IF EXISTS to avoid transaction aborts
    op.execute("DROP INDEX IF EXISTS missions_workspace_status_idx")
    op.create_index("tasks_workspace_status_idx", "tasks", ["workspace_id", "status"])

    op.execute("DROP INDEX IF EXISTS missions_assignee_idx")
    op.create_index("tasks_agent_idx", "tasks", ["agent_id"])

    op.execute("DROP INDEX IF EXISTS missions_creator_idx")
    op.create_index("tasks_creator_idx", "tasks", ["creator_id", "created_at"])


def downgrade():
    pass  # no rollback in greenfield
