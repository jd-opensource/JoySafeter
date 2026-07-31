"""repair task trigger_id column on already-migrated databases

Revision ID: 20260731_000003
Revises: 20260731_000002
Create Date: 2026-07-31 19:10:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import context, op

revision: str = "20260731_000003"
down_revision: Union[str, None] = "20260731_000002"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

TASKS_TABLE_NAME = "joysafeter_tasks"


def _has_column(column_name: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    columns = inspect(bind).get_columns(TASKS_TABLE_NAME)
    return any(column["name"] == column_name for column in columns)


def _has_index(index_name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    indexes = inspect(bind).get_indexes(TASKS_TABLE_NAME)
    return any(index["name"] == index_name for index in indexes)


def upgrade() -> None:
    if _has_column("trigger_id"):
        pass
    elif _has_column("schedule_id"):
        if _has_index("idx_ct_schedule"):
            op.drop_index("idx_ct_schedule", table_name=TASKS_TABLE_NAME)
        op.alter_column(TASKS_TABLE_NAME, "schedule_id", new_column_name="trigger_id")
    else:
        op.add_column(TASKS_TABLE_NAME, sa.Column("trigger_id", sa.UUID(), nullable=True))

    if not _has_index("idx_ct_trigger"):
        op.create_index("idx_ct_trigger", TASKS_TABLE_NAME, ["trigger_id"])


def downgrade() -> None:
    if _has_index("idx_ct_trigger"):
        op.drop_index("idx_ct_trigger", table_name=TASKS_TABLE_NAME)
    if _has_column("trigger_id") and not _has_column("schedule_id"):
        op.alter_column(TASKS_TABLE_NAME, "trigger_id", new_column_name="schedule_id")
        op.create_index("idx_ct_schedule", TASKS_TABLE_NAME, ["schedule_id"])
