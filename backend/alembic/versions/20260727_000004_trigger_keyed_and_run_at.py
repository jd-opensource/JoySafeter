"""trigger keyed session mode + one-off run_at: add session_key, run_at columns

Revision ID: 20260727_000004
Revises: 20260727_000003
Create Date: 2026-07-27

- ``session_key``  a payload-rendered template ({{ token.path }}) that buckets
  ``keyed`` session mode — one reused session per rendered key (e.g. one thread
  per customer/chat/repo for a shared webhook).
- ``run_at``       a one-off fire instant. A cron-type trigger may carry either a
  recurring ``cron_expr`` OR a single ``run_at``; a one-off fires once then
  parks (next_run_at → NULL).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260727_000004"
down_revision: Union[str, None] = "20260727_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_triggers", sa.Column("session_key", sa.Text(), nullable=True))
    op.add_column("joysafeter_triggers", sa.Column("run_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("joysafeter_triggers", "run_at")
    op.drop_column("joysafeter_triggers", "session_key")
