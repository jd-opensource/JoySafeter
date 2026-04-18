"""remove_mission_blocked_status

Revision ID: d6d5d4d3d2d1
Revises: c5c4c3c2c1c0
Create Date: 2026-04-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "d6d5d4d3d2d1"
down_revision: Union[str, None] = "c5c4c3c2c1c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Move any blocked missions to todo before dropping the enum value
    op.execute("UPDATE missions SET status = 'todo' WHERE status = 'blocked'")

    # Drop the default before changing type — PG can't auto-cast the default
    op.execute("ALTER TABLE missions ALTER COLUMN status DROP DEFAULT")

    # PostgreSQL cannot DROP a value from an existing enum, so recreate it
    op.execute("ALTER TYPE missionstatus RENAME TO missionstatus_old")
    op.execute(
        "CREATE TYPE missionstatus AS ENUM "
        "('backlog','todo','in_progress','in_review','done','cancelled')"
    )
    op.execute(
        "ALTER TABLE missions "
        "ALTER COLUMN status TYPE missionstatus "
        "USING status::text::missionstatus"
    )
    op.execute("DROP TYPE missionstatus_old")

    # Restore the default
    op.execute("ALTER TABLE missions ALTER COLUMN status SET DEFAULT 'backlog'")


def downgrade() -> None:
    op.execute("ALTER TABLE missions ALTER COLUMN status DROP DEFAULT")

    op.execute("ALTER TYPE missionstatus RENAME TO missionstatus_old")
    op.execute(
        "CREATE TYPE missionstatus AS ENUM "
        "('backlog','todo','in_progress','in_review','done','blocked','cancelled')"
    )
    op.execute(
        "ALTER TABLE missions "
        "ALTER COLUMN status TYPE missionstatus "
        "USING status::text::missionstatus"
    )
    op.execute("DROP TYPE missionstatus_old")

    op.execute("ALTER TABLE missions ALTER COLUMN status SET DEFAULT 'backlog'")
