"""add dispatched and approval_wait to execution_status enum

Revision ID: 778bc9cdef07
Revises: 667ab8bcde06
Create Date: 2026-04-22 13:00:00.000000+00:00

Changes:
- execution_status enum: add 'dispatched' and 'approval_wait' values
  These states are actively written by execution_runner.py / definitions.py
  but were missing from the DB enum, causing runtime errors on first write.

NOTE: ALTER TYPE ... ADD VALUE requires PostgreSQL 9.1+.
      Enum values cannot be removed in PostgreSQL (downgrade is a no-op).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "778bc9cdef07"
down_revision: Union[str, None] = "667ab8bcde06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'dispatched'")
    op.execute("ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'approval_wait'")


def downgrade() -> None:
    pass  # Cannot remove enum values in PostgreSQL
