"""fix tasks schedule_id FK: point to joysafeter_schedules (not triggers)

Revision ID: 20260724_000001
Revises: 20260723_000013
Create Date: 2026-07-24

Migration 20260723_000013 changed the FK on joysafeter_tasks.schedule_id
from joysafeter_schedules to joysafeter_triggers. However the scheduler
loop code (SchedulerLoop + JoySafeterSchedule model) still reads/writes
joysafeter_schedules, so every scheduled task INSERT fails with:

    ForeignKeyViolationError: Key (schedule_id)=... is not present
    in table "joysafeter_triggers"

Fix: point the FK back to joysafeter_schedules.
"""

from typing import Union

from alembic import op

revision: str = "20260724_000001"
down_revision: Union[str, None] = "20260723_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the wrong FK (points to triggers)
    op.drop_constraint(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_triggers"),
        "joysafeter_tasks",
        type_="foreignkey",
    )
    # Recreate FK pointing to the correct table
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        "joysafeter_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_schedules"),
        "joysafeter_tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_tasks_schedule_id_joysafeter_triggers"),
        "joysafeter_tasks",
        "joysafeter_triggers",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
