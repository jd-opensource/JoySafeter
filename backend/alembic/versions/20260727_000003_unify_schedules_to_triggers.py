"""unify schedules API storage onto cron triggers

Revision ID: 20260727_000003
Revises: 20260727_000002
Create Date: 2026-07-27 21:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260727_000003"
down_revision: Union[str, Sequence[str], None] = "20260727_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO joysafeter_triggers (
            id, created_at, updated_at, name, description, type, agent_id,
            prompt_template, system_prompt, environment_ref, enabled,
            session_mode, pinned_session_id, reusable_session_id, filter, config,
            timeout_sec, max_retries, cron_expr, timezone, concurrency_policy,
            next_run_at, last_fired_slot, locked_by, locked_at, project_id,
            user_id, org_id, last_attempt_at, last_success_at, last_error,
            consecutive_failures, last_task_id, last_session_id, last_payload
        )
        SELECT
            s.id, s.created_at, s.updated_at, s.name, s.description, 'cron', s.agent_id,
            s.prompt, s.system_prompt, s.environment_ref, s.enabled,
            COALESCE(s.session_mode, 'fresh'), s.pinned_session_id, s.reusable_session_id,
            '{}'::jsonb,
            jsonb_build_object(
                'cron_expr', s.cron_expr,
                'timezone', s.timezone,
                'concurrency_policy', s.concurrency_policy,
                'next_run_at', CASE WHEN s.next_run_at IS NULL THEN NULL ELSE to_jsonb(s.next_run_at::text) END,
                'last_fired_slot', CASE WHEN s.last_fired_slot IS NULL THEN NULL ELSE to_jsonb(s.last_fired_slot::text) END
            ),
            s.timeout_sec, s.max_retries, s.cron_expr, s.timezone, s.concurrency_policy,
            s.next_run_at, s.last_fired_slot, s.locked_by, s.locked_at, s.project_id,
            s.user_id, s.org_id, s.last_attempt_at, s.last_success_at, s.last_error,
            s.consecutive_failures, s.last_task_id, s.last_session_id, s.last_payload
          FROM joysafeter_schedules s
        ON CONFLICT (id) DO UPDATE SET
            updated_at = EXCLUDED.updated_at,
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            type = 'cron',
            agent_id = EXCLUDED.agent_id,
            prompt_template = EXCLUDED.prompt_template,
            system_prompt = EXCLUDED.system_prompt,
            environment_ref = EXCLUDED.environment_ref,
            enabled = EXCLUDED.enabled,
            session_mode = EXCLUDED.session_mode,
            pinned_session_id = EXCLUDED.pinned_session_id,
            reusable_session_id = EXCLUDED.reusable_session_id,
            config = EXCLUDED.config,
            timeout_sec = EXCLUDED.timeout_sec,
            max_retries = EXCLUDED.max_retries,
            cron_expr = EXCLUDED.cron_expr,
            timezone = EXCLUDED.timezone,
            concurrency_policy = EXCLUDED.concurrency_policy,
            next_run_at = EXCLUDED.next_run_at,
            last_fired_slot = EXCLUDED.last_fired_slot,
            locked_by = EXCLUDED.locked_by,
            locked_at = EXCLUDED.locked_at,
            project_id = EXCLUDED.project_id,
            user_id = EXCLUDED.user_id,
            org_id = EXCLUDED.org_id,
            last_attempt_at = EXCLUDED.last_attempt_at,
            last_success_at = EXCLUDED.last_success_at,
            last_error = EXCLUDED.last_error,
            consecutive_failures = EXCLUDED.consecutive_failures,
            last_task_id = EXCLUDED.last_task_id,
            last_session_id = EXCLUDED.last_session_id,
            last_payload = EXCLUDED.last_payload
        """
    )
    op.execute("ALTER TABLE joysafeter_tasks DROP CONSTRAINT IF EXISTS fk_joysafeter_tasks_schedule_id_joysafeter_schedules")
    op.execute("ALTER TABLE joysafeter_tasks DROP CONSTRAINT IF EXISTS fk_joysafeter_tasks_schedule_id_joysafeter_triggers")
    op.execute(
        """
        ALTER TABLE joysafeter_tasks
        ADD CONSTRAINT fk_joysafeter_tasks_schedule_id_joysafeter_triggers
        FOREIGN KEY (schedule_id) REFERENCES joysafeter_triggers (id)
        ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE joysafeter_tasks DROP CONSTRAINT IF EXISTS fk_joysafeter_tasks_schedule_id_joysafeter_triggers")
    op.execute("ALTER TABLE joysafeter_tasks DROP CONSTRAINT IF EXISTS fk_joysafeter_tasks_schedule_id_joysafeter_schedules")
    op.execute(
        """
        ALTER TABLE joysafeter_tasks
        ADD CONSTRAINT fk_joysafeter_tasks_schedule_id_joysafeter_schedules
        FOREIGN KEY (schedule_id) REFERENCES joysafeter_schedules (id)
        ON DELETE SET NULL
        """
    )
