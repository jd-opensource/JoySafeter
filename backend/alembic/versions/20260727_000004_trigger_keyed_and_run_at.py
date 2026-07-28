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
    # Keyed session mode looks up "newest idle session for this agent + rendered
    # key" on every keyed fire. Without an expression index that JSONB ->> match
    # is a seq scan over sessions; index it partially (only keyed sessions carry
    # the metadata key) so the lookup stays an index scan as sessions grow.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_csess_trigger_session_key
        ON joysafeter_sessions (agent_id, ((metadata->>'trigger_session_key')))
        WHERE metadata ? 'trigger_session_key'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_csess_trigger_session_key")
    op.drop_column("joysafeter_triggers", "run_at")
    op.drop_column("joysafeter_triggers", "session_key")
