"""soft-delete triggers and preserve run history

Revision ID: 20260729_000001
Revises: 20260728_000002
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import context, op

revision: str = "20260729_000001"
down_revision: Union[str, None] = "20260728_000002"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

TABLE_NAME = "joysafeter_triggers"
TASKS_TABLE_NAME = "joysafeter_tasks"


def _has_column(column_name: str, table_name: str = TABLE_NAME) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    columns = inspect(bind).get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def _has_index(index_name: str, table_name: str = TABLE_NAME) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    indexes = inspect(bind).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _has_unique_constraint(constraint_name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    constraints = inspect(bind).get_unique_constraints(TABLE_NAME)
    return any(constraint["name"] == constraint_name for constraint in constraints)


def _add_column_if_missing(column: sa.Column) -> None:
    if not _has_column(column.name):
        op.add_column(TABLE_NAME, column)


def _repair_task_trigger_column() -> None:
    if _has_column("trigger_id", TASKS_TABLE_NAME):
        pass
    elif _has_column("schedule_id", TASKS_TABLE_NAME):
        if _has_index("idx_ct_schedule", TASKS_TABLE_NAME):
            op.drop_index("idx_ct_schedule", table_name=TASKS_TABLE_NAME)
        op.alter_column(TASKS_TABLE_NAME, "schedule_id", new_column_name="trigger_id")
    else:
        op.add_column(TASKS_TABLE_NAME, sa.Column("trigger_id", sa.UUID(), nullable=True))

    if not _has_index("idx_ct_trigger", TASKS_TABLE_NAME):
        op.create_index("idx_ct_trigger", TASKS_TABLE_NAME, ["trigger_id"])


def upgrade() -> None:
    _repair_task_trigger_column()

    _add_column_if_missing(sa.Column("pending_slot_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(sa.Column("slot_attempts", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing(sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(sa.Column("disabled_reason", sa.Text(), nullable=True))
    _add_column_if_missing(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        WITH ranked_global_triggers AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY name
                    ORDER BY
                        enabled DESC,
                        COALESCE(last_success_at, last_attempt_at, updated_at, created_at) DESC,
                        created_at ASC,
                        id ASC
                ) AS duplicate_rank
              FROM joysafeter_triggers
             WHERE project_id IS NULL
               AND deleted_at IS NULL
        )
        UPDATE joysafeter_triggers AS trigger
           SET deleted_at = now(),
               enabled = false,
               next_run_at = NULL,
               locked_by = NULL,
               locked_at = NULL,
               pending_slot_at = NULL,
               slot_attempts = 0,
               disabled_reason = COALESCE(
                   trigger.disabled_reason,
                   'soft-deleted by 20260729_000001: duplicate global trigger name'
               ),
               updated_at = now(),
               config = jsonb_strip_nulls(
                   COALESCE(trigger.config, '{}'::jsonb)
                   || jsonb_build_object(
                       'enabled', false,
                       'next_run_at', NULL,
                       'locked_by', NULL,
                       'locked_at', NULL,
                       'pending_slot_at', NULL,
                       'slot_attempts', 0,
                       'deleted_at', now(),
                       'deleted_reason', 'duplicate_global_trigger_name'
                   )
               )
          FROM ranked_global_triggers AS ranked
         WHERE trigger.id = ranked.id
           AND ranked.duplicate_rank > 1
        """
    )

    if _has_index("idx_joysafeter_triggers_cron_due"):
        op.drop_index("idx_joysafeter_triggers_cron_due", table_name="joysafeter_triggers")
    op.create_index(
        "idx_joysafeter_triggers_cron_due",
        "joysafeter_triggers",
        ["next_run_at"],
        postgresql_where=sa.text("enabled IS TRUE AND type = 'cron' AND deleted_at IS NULL"),
    )

    if _has_unique_constraint("uq_joysafeter_triggers_project_name"):
        op.drop_constraint("uq_joysafeter_triggers_project_name", "joysafeter_triggers", type_="unique")
    elif _has_index("uq_joysafeter_triggers_project_name"):
        op.drop_index("uq_joysafeter_triggers_project_name", table_name="joysafeter_triggers")
    op.create_index(
        "uq_joysafeter_triggers_project_name",
        "joysafeter_triggers",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_triggers_global_name",
        "joysafeter_triggers",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_joysafeter_triggers_global_name", table_name="joysafeter_triggers")
    op.drop_index("uq_joysafeter_triggers_project_name", table_name="joysafeter_triggers")
    op.create_unique_constraint(
        "uq_joysafeter_triggers_project_name",
        "joysafeter_triggers",
        ["project_id", "name"],
    )

    op.drop_index("idx_joysafeter_triggers_cron_due", table_name="joysafeter_triggers")
    op.create_index(
        "idx_joysafeter_triggers_cron_due",
        "joysafeter_triggers",
        ["next_run_at"],
        postgresql_where=sa.text("enabled IS TRUE AND type = 'cron'"),
    )

    op.drop_column("joysafeter_triggers", "deleted_at")
