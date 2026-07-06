"""add session user.message idempotency index

Revision ID: 20260703_000008
Revises: 20260703_000007
Create Date: 2026-07-03
"""

from alembic import op

revision = "20260703_000008"
down_revision = "20260703_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cse_session_user_message_idempotency_key
        ON joysafeter_session_events (session_id, ((payload->>'_idempotency_key')))
        WHERE event_type = 'user.message' AND payload ? '_idempotency_key'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cse_session_user_message_idempotency_key")
