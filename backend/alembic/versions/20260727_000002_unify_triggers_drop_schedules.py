"""unify triggers: rename tasks.schedule_id -> trigger_id, drop joysafeter_schedules

Revision ID: 20260727_000002
Revises: 20260725_000002
Create Date: 2026-07-27

Cron scheduling is now a ``type='cron'`` row in ``joysafeter_triggers`` (the
single unified trigger table). The legacy ``joysafeter_schedules`` table and the
mismatched ``joysafeter_tasks.schedule_id -> joysafeter_schedules`` foreign key
are removed. The task back-reference column is renamed to ``trigger_id`` and
repointed at ``joysafeter_triggers`` so a fired trigger's task INSERT no longer
violates the FK.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260727_000002"
down_revision: Union[str, None] = "20260725_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the stale FK (schedule_id -> joysafeter_schedules).
    op.drop_constraint(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        type_="foreignkey",
    )
    # 2. Rename the back-reference column and its index.
    op.drop_index("idx_ct_schedule", table_name="joysafeter_tasks")
    op.alter_column("joysafeter_tasks", "schedule_id", new_column_name="trigger_id")
    op.create_index("idx_ct_trigger", "joysafeter_tasks", ["trigger_id"])
    # 3. Repoint the FK at the unified triggers table.
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_trigger_id_joysafeter_triggers"),
        "joysafeter_tasks",
        "joysafeter_triggers",
        ["trigger_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 4. Drop the now-unused legacy table (cascades its indexes/constraints).
    op.drop_table("joysafeter_schedules")


def downgrade() -> None:
    # Recreate the legacy schedules table (schema as of 20260723_000012).
    op.create_table(
        "joysafeter_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("environment_ref", sa.String(length=255), nullable=True),
        sa.Column("timeout_sec", sa.Integer(), nullable=False, server_default="7200"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("cron_expr", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("concurrency_policy", sa.String(length=16), nullable=False, server_default="allow"),
        sa.Column("session_mode", sa.String(length=16), nullable=False, server_default="fresh"),
        sa.Column("pinned_session_id", sa.UUID(), nullable=True),
        sa.Column("reusable_session_id", sa.UUID(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_task_id", sa.UUID(), nullable=True),
        sa.Column("last_session_id", sa.UUID(), nullable=True),
        sa.Column("last_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.String(length=255), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["joysafeter_agents.id"], name=op.f("fk_joysafeter_schedules_agent_id_joysafeter_agents")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["joysafeter_organization_projects.id"],
            name=op.f("fk_joysafeter_schedules_project_id_joysafeter_organization_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["pinned_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_schedules_pinned_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reusable_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_schedules_reusable_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_task_id"],
            ["joysafeter_tasks.id"],
            name=op.f("fk_joysafeter_schedules_last_task_id_joysafeter_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_schedules_last_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_joysafeter_schedules")),
        sa.UniqueConstraint("project_id", "name", name="uq_joysafeter_schedules_project_name"),
    )
    op.create_index(
        "idx_joysafeter_schedules_due",
        "joysafeter_schedules",
        ["next_run_at"],
        postgresql_where=sa.text("enabled IS TRUE"),
    )
    op.create_index("idx_joysafeter_schedules_project", "joysafeter_schedules", ["project_id"])
    op.create_index("idx_joysafeter_schedules_session_mode", "joysafeter_schedules", ["session_mode"])

    # Reverse the tasks column/FK back to joysafeter_schedules.
    op.drop_constraint(
        op.f("fk_joysafeter_tasks_trigger_id_joysafeter_triggers"),
        "joysafeter_tasks",
        type_="foreignkey",
    )
    op.drop_index("idx_ct_trigger", table_name="joysafeter_tasks")
    op.alter_column("joysafeter_tasks", "trigger_id", new_column_name="schedule_id")
    op.create_index("idx_ct_schedule", "joysafeter_tasks", ["schedule_id"])
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        "joysafeter_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
