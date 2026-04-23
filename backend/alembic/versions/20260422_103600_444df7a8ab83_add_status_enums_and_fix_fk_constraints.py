"""add status enums and fix FK constraints

Revision ID: 556fa9cacd05
Revises: 444df7a8ab83
Create Date: 2026-04-22 10:36:00.000000+00:00

Changes:
- Create DB enum types: agent_status, agent_version_status, agent_release_status,
  agent_run_status, execution_status
- Migrate status columns from varchar to enum types
- Fix agents.created_by  ondelete: SET NULL → CASCADE  (NOT NULL + SET NULL = crash)
- Fix agent_versions.created_by  ondelete: SET NULL → CASCADE (same issue)
- Fix thread_messages.run_id / execution_id FKs: add ondelete=SET NULL
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "556fa9cacd05"
down_revision: Union[str, None] = "444df7a8ab83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _create_enum(name: str, *values: str) -> None:
    """CREATE TYPE <name> AS ENUM (...) — idempotent via IF NOT EXISTS."""
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute(f"CREATE TYPE {name} AS ENUM ({quoted})")


def _drop_enum(name: str) -> None:
    op.execute(f"DROP TYPE IF EXISTS {name}")


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create enum types
    # ------------------------------------------------------------------
    _create_enum("agent_status", "draft", "active", "archived")
    _create_enum("agent_version_status", "draft", "frozen")
    _create_enum("agent_release_status", "building", "ready", "failed", "retired")
    _create_enum("agent_run_status", "queued", "running", "succeeded", "failed", "cancelled")
    _create_enum("execution_status", "pending", "running", "succeeded", "failed", "cancelled")

    # ------------------------------------------------------------------
    # 2. Migrate status columns varchar → enum  (using USING cast)
    # ------------------------------------------------------------------
    # agents
    op.execute("ALTER TABLE agents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agents ALTER COLUMN status TYPE agent_status USING status::agent_status")
    op.execute("ALTER TABLE agents ALTER COLUMN status SET DEFAULT 'draft'::agent_status")

    # agent_versions
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status TYPE agent_version_status USING status::agent_version_status")
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status SET DEFAULT 'draft'::agent_version_status")

    # agent_releases
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status TYPE agent_release_status USING status::agent_release_status")
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status SET DEFAULT 'building'::agent_release_status")

    # agent_runs
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status TYPE agent_run_status USING status::agent_run_status")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status SET DEFAULT 'queued'::agent_run_status")

    # executions
    op.execute("ALTER TABLE executions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE executions "
        "ALTER COLUMN status TYPE execution_status "
        "USING (CASE "
        "  WHEN status IN ('queued', 'dispatched') THEN 'pending' "
        "  WHEN status = 'completed' THEN 'succeeded' "
        "  ELSE status "
        "END)::execution_status"
    )
    op.execute("ALTER TABLE executions ALTER COLUMN status SET DEFAULT 'pending'::execution_status")

    # 3. Fix agents.created_by: drop old FK (no ondelete) → re-add CASCADE
    #    The actual name in DB is "fk_agents_created_by_user".
    # ------------------------------------------------------------------
    op.drop_constraint("fk_agents_created_by_user", "agents", type_="foreignkey")
    op.create_foreign_key(
        "fk_agents_created_by",
        "agents",
        "user",
        ["created_by"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 4. Fix agent_versions.created_by (same issue, actual: "fk_agent_versions_created_by_user")
    # ------------------------------------------------------------------
    op.drop_constraint("fk_agent_versions_created_by_user", "agent_versions", type_="foreignkey")
    op.create_foreign_key(
        "fk_agent_versions_created_by",
        "agent_versions",
        "user",
        ["created_by"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 5. Fix thread_messages.run_id / execution_id: drop old FKs (no
    #    ondelete), re-add with ondelete=SET NULL.
    #    Old names from migration ee55ff66aa77: fk_messages_run / fk_messages_execution
    # ------------------------------------------------------------------
    op.drop_constraint("fk_messages_run", "thread_messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_thread_messages_run_id",
        "thread_messages",
        "agent_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("fk_messages_execution", "thread_messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_thread_messages_execution_id",
        "thread_messages",
        "executions",
        ["execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Restore thread_messages FKs without ondelete
    op.drop_constraint("fk_thread_messages_execution_id", "thread_messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_execution", "thread_messages", "executions", ["execution_id"], ["id"]
    )

    op.drop_constraint("fk_thread_messages_run_id", "thread_messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_run", "thread_messages", "agent_runs", ["run_id"], ["id"]
    )

    # Restore agent_versions.created_by FK without ondelete
    op.drop_constraint("fk_agent_versions_created_by", "agent_versions", type_="foreignkey")
    op.create_foreign_key(
        None, "agent_versions", "user", ["created_by"], ["id"]
    )

    # Restore agents.created_by FK without ondelete
    op.drop_constraint("fk_agents_created_by", "agents", type_="foreignkey")
    op.create_foreign_key(
        None, "agents", "user", ["created_by"], ["id"]
    )

    # Revert status columns enum → varchar
    # executions
    op.execute("ALTER TABLE executions ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE executions ALTER COLUMN status TYPE varchar(20) USING status::text")
    op.execute("ALTER TABLE executions ALTER COLUMN status SET DEFAULT 'queued'")

    # agent_runs
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status TYPE varchar(20) USING status::text")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status SET DEFAULT 'queued'")

    # agent_releases
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status TYPE varchar(20) USING status::text")
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status SET DEFAULT 'building'")

    # agent_versions
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status TYPE varchar(20) USING status::text")
    op.execute("ALTER TABLE agent_versions ALTER COLUMN status SET DEFAULT 'draft'")

    # agents
    op.execute("ALTER TABLE agents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE agents ALTER COLUMN status TYPE varchar(20) USING status::text")
    op.execute("ALTER TABLE agents ALTER COLUMN status SET DEFAULT 'draft'")

    # Drop enum types
    _drop_enum("execution_status")
    _drop_enum("agent_run_status")
    _drop_enum("agent_release_status")
    _drop_enum("agent_version_status")
    _drop_enum("agent_status")
