"""add scheduler: joysafeter_schedules + tasks.schedule_id

Adds the cron scheduler's ``joysafeter_schedules`` table and a nullable
``schedule_id`` FK on ``joysafeter_tasks`` linking a fired task back to the
schedule that produced it (execution history is the task table itself, tagged
with schedule_id — no separate schedule_runs table).

The scheduler is a thin cron trigger: at each fire it submits a task through
the same path the HTTP API uses, so the Rust task engine's lease/fencing/
watchdog/idempotency/retry all apply unchanged. Exactly-once firing across
worker replicas is enforced by the task's existing idempotency unique
constraint (key = ``sched:{schedule_id}:{aligned_slot_epoch}``).

Revision ID: 20260710_000011
Revises: 20260703_000010
Create Date: 2026-07-10 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260710_000011"
down_revision: Union[str, None] = "20260703_000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("environment_ref", sa.String(length=255), nullable=True),
        sa.Column("timeout_sec", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("cron_expr", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("concurrency_policy", sa.String(length=16), nullable=False, server_default="allow"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.String(length=255), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["joysafeter_agents.id"],
            name=op.f("fk_joysafeter_schedules_agent_id_joysafeter_agents"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["joysafeter_organization_projects.id"],
            name=op.f("fk_joysafeter_schedules_project_id_joysafeter_organization_projects"),
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

    op.add_column("joysafeter_tasks", sa.Column("schedule_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        "joysafeter_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_ct_schedule", "joysafeter_tasks", ["schedule_id"])


def downgrade() -> None:
    op.drop_index("idx_ct_schedule", table_name="joysafeter_tasks")
    op.drop_constraint(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        type_="foreignkey",
    )
    op.drop_column("joysafeter_tasks", "schedule_id")

    op.drop_index("idx_joysafeter_schedules_project", table_name="joysafeter_schedules")
    op.drop_index("idx_joysafeter_schedules_due", table_name="joysafeter_schedules")
    op.drop_table("joysafeter_schedules")
