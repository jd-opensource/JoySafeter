"""rename mission enums to task enums

Revision ID: 333df7a8ab82
Revises: h1i2j3k4l5m6
Create Date: 2026-04-22 10:15:51.632056+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "333df7a8ab82"
down_revision: Union[str, None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'missionstatus') THEN
            ALTER TYPE missionstatus RENAME TO taskstatus;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'missionpriority') THEN
            ALTER TYPE missionpriority RENAME TO taskpriority;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') THEN
            ALTER TYPE taskstatus RENAME TO missionstatus;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskpriority') THEN
            ALTER TYPE taskpriority RENAME TO missionpriority;
        END IF;
    END $$;
    """)
