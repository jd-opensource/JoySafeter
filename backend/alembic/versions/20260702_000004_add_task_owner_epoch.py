"""add task owner_epoch fencing token (Foundation 1 — fencing)

Adds ``owner_epoch`` to ``joysafeter_tasks`` plus a dedicated Postgres
``SEQUENCE``. Each →RUNNING claim stamps a fresh ``nextval`` — a globally
monotonic fencing token for that ownership grant. Every mutating write for a
running task is conditioned on the epoch it was granted; a stalled zombie whose
task was reclaimed and re-run (bumping the epoch) writes with a stale token,
matches zero rows, and is dropped instead of corrupting the row a new owner now
holds.

Postgres SEQUENCE is the only durable monotonic source available (Redis has no
durable monotonic primitive, and a task-local counter cannot survive a requeue
across instances).

Revision ID: 20260702_000004
Revises: 20260702_000003
Create Date: 2026-07-02 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260702_000004"
down_revision: Union[str, None] = "20260702_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEQUENCE_NAME = "joysafeter_task_owner_epoch_seq"


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence(SEQUENCE_NAME)))
    op.add_column("joysafeter_tasks", sa.Column("owner_epoch", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("joysafeter_tasks", "owner_epoch")
    op.execute(sa.schema.DropSequence(sa.Sequence(SEQUENCE_NAME)))
