"""unify cron and webhook agent triggers

Revision ID: 20260723_000013
Revises: 20260723_000012
Create Date: 2026-07-23 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_000013"
down_revision: Union[str, None] = "20260723_000012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_triggers", sa.Column("secret_ref", sa.String(length=255), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("secret_key", sa.String(length=255), nullable=True))
    op.add_column(
        "joysafeter_triggers",
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.add_column("joysafeter_triggers", sa.Column("cron_expr", sa.String(length=255), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column(
        "joysafeter_triggers",
        sa.Column("concurrency_policy", sa.String(length=16), nullable=False, server_default="allow"),
    )
    op.add_column("joysafeter_triggers", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("last_fired_slot", sa.DateTime(timezone=True), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("locked_by", sa.Text(), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE joysafeter_triggers
           SET secret_ref = secret,
               secret_key = 'WEBHOOK_SECRET',
               config = jsonb_build_object(
                   'secret_ref', secret,
                   'secret_key', 'WEBHOOK_SECRET',
                   'auth_methods', jsonb_build_array('hmac', 'bearer', 'token'),
                   'dedupe_header', 'x-joysafeter-delivery'
               )
         WHERE type = 'webhook' AND secret IS NOT NULL
        """
    )

    op.execute(
        """
        INSERT INTO joysafeter_triggers (
            id, name, description, type, agent_id, prompt_template, system_prompt, environment_ref,
            enabled, session_mode, pinned_session_id, reusable_session_id, filter, config,
            timeout_sec, max_retries, cron_expr, timezone, concurrency_policy, next_run_at,
            last_fired_slot, last_attempt_at, last_success_at, last_error, consecutive_failures,
            last_task_id, last_session_id, last_payload, project_id, user_id, org_id,
            locked_by, locked_at, created_at, updated_at
        )
        SELECT
            id, name, description, 'cron', agent_id, prompt, system_prompt, environment_ref,
            enabled, session_mode, pinned_session_id, reusable_session_id, '{}'::jsonb,
            jsonb_build_object(
                'cron_expr', cron_expr,
                'timezone', timezone,
                'concurrency_policy', concurrency_policy,
                'next_run_at', next_run_at,
                'last_fired_slot', last_fired_slot
            ),
            timeout_sec, max_retries, cron_expr, timezone, concurrency_policy, next_run_at,
            last_fired_slot, last_attempt_at, last_success_at, last_error, consecutive_failures,
            last_task_id, last_session_id, last_payload, project_id, user_id, org_id,
            locked_by, locked_at, created_at, updated_at
          FROM joysafeter_schedules
        ON CONFLICT (project_id, name) DO NOTHING
        """
    )

    op.create_index("idx_joysafeter_triggers_cron_due", "joysafeter_triggers", ["next_run_at"], postgresql_where=sa.text("enabled IS TRUE AND type = 'cron'"))
    op.drop_constraint(op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"), "joysafeter_tasks", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_triggers"),
        "joysafeter_tasks",
        "joysafeter_triggers",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("joysafeter_triggers", "secret")


def downgrade() -> None:
    op.add_column("joysafeter_triggers", sa.Column("secret", sa.String(length=255), nullable=True))
    op.execute("UPDATE joysafeter_triggers SET secret = secret_ref WHERE type = 'webhook'")
    op.drop_constraint(op.f("fk_joysafeter_tasks_schedule_id_joysafeter_triggers"), "joysafeter_tasks", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        "joysafeter_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("idx_joysafeter_triggers_cron_due", table_name="joysafeter_triggers")
    for column in (
        "locked_at",
        "locked_by",
        "last_fired_slot",
        "next_run_at",
        "concurrency_policy",
        "timezone",
        "cron_expr",
        "config",
        "secret_key",
        "secret_ref",
    ):
        op.drop_column("joysafeter_triggers", column)
