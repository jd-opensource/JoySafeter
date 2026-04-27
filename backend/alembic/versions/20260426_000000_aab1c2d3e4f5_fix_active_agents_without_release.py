"""fix agents with status='active' but no active release

Revision ID: aab1c2d3e4f5
Revises: 990de1ef09
Create Date: 2026-04-26 00:00:00.000000+00:00

Changes:
- Data-only migration: revert agents to 'draft' when status is 'active'
  but active_release_id is NULL (out-of-sync state from retire_release
  not syncing status prior to this fix).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "aab1c2d3e4f5"
down_revision: Union[str, None] = "990de1ef09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE agents SET status = 'draft' " "WHERE status = 'active' AND active_release_id IS NULL")


def downgrade() -> None:
    pass
