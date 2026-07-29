"""trigger retry/dead-letter state: pending_slot_at, slot_attempts, auto_disabled_at, disabled_reason

Revision ID: 20260727_000003
Revises: 20260727_000002
Create Date: 2026-07-27

Adds the control-plane reliability columns the cron scheduler needs to retry a
failed slot with backoff and to dead-letter (auto-disable) a trigger after
repeated failures, instead of silently skipping the slot.

- ``pending_slot_at``  the cron slot instant currently being attempted/retried
  (NULL when idle or already advanced). Lets a retry reuse the same logical slot
  so its idempotency key stays stable.
- ``slot_attempts``    attempts made for ``pending_slot_at`` (drives backoff and
  the attempt-suffixed idempotency key on retries).
- ``auto_disabled_at`` when the scheduler auto-disabled the trigger after
  crossing the consecutive-failure threshold.
- ``disabled_reason``  human-readable reason for the auto-disable.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260727_000003"
down_revision: Union[str, None] = "20260727_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_triggers",
        sa.Column("pending_slot_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_triggers",
        sa.Column("slot_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "joysafeter_triggers",
        sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_triggers",
        sa.Column("disabled_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("joysafeter_triggers", "disabled_reason")
    op.drop_column("joysafeter_triggers", "auto_disabled_at")
    op.drop_column("joysafeter_triggers", "slot_attempts")
    op.drop_column("joysafeter_triggers", "pending_slot_at")
