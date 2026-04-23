"""unify status vocabulary queued to pending and building to pending

Revision ID: 667ab8bcde06
Revises: 556fa9cacd05
Create Date: 2026-04-22 12:00:00.000000+00:00

Changes:
- agent_run_status enum: rename 'queued' -> 'pending'
- agent_release_status enum: rename 'building' -> 'pending'

NOTE: ALTER TYPE ... RENAME VALUE requires PostgreSQL 10+.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "667ab8bcde06"
down_revision: Union[str, None] = "556fa9cacd05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE agent_run_status RENAME VALUE 'queued' TO 'pending'")
    op.execute("ALTER TYPE agent_release_status RENAME VALUE 'building' TO 'pending'")


def downgrade() -> None:
    op.execute("ALTER TYPE agent_run_status RENAME VALUE 'pending' TO 'queued'")
    op.execute("ALTER TYPE agent_release_status RENAME VALUE 'pending' TO 'building'")
