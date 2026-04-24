"""remove pending from agent_release_status enum

Revision ID: 889cd0def08
Revises: 778bc9cdef07
Create Date: 2026-04-24 00:00:00.000000+00:00

Changes:
- agent_release_status enum: remove 'pending' (never used in practice)
- Set server_default to 'ready' (matches ORM default and service behavior)

PostgreSQL cannot DROP a value from an enum, so we recreate the type.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "889cd0def08"
down_revision: Union[str, None] = "778bc9cdef07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the default so the column has no dependency on the enum during swap
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status DROP DEFAULT")

    # 2. Rename old enum out of the way
    op.execute("ALTER TYPE agent_release_status RENAME TO agent_release_status_old")

    # 3. Create new enum without 'pending'
    op.execute("CREATE TYPE agent_release_status AS ENUM ('ready', 'failed', 'retired')")

    # 4. Swap column type (no rows should have 'pending'; fail loudly if they do)
    op.execute(
        "ALTER TABLE agent_releases "
        "ALTER COLUMN status TYPE agent_release_status "
        "USING status::text::agent_release_status"
    )

    # 5. Set correct default
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status SET DEFAULT 'ready'::agent_release_status")

    # 6. Drop old enum
    op.execute("DROP TYPE agent_release_status_old")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE agent_release_status RENAME TO agent_release_status_old")
    op.execute("CREATE TYPE agent_release_status AS ENUM ('pending', 'ready', 'failed', 'retired')")
    op.execute(
        "ALTER TABLE agent_releases "
        "ALTER COLUMN status TYPE agent_release_status "
        "USING status::text::agent_release_status"
    )
    op.execute("ALTER TABLE agent_releases ALTER COLUMN status SET DEFAULT 'pending'::agent_release_status")
    op.execute("DROP TYPE agent_release_status_old")
