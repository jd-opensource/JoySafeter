"""add running-task lease (Foundation 1 — fast reclaim)

Adds ``owner_instance_id`` + ``lease_expires_at`` to ``joysafeter_tasks``. The
orchestrator instance that transitions a task to ``running`` stamps its
instance id and a short lease; it renews the lease while it holds the task.
When an instance crashes, its running tasks' leases lapse and any instance's
watchdog reclaims them in seconds — instead of waiting for the ~2h
``timeout_sec`` upper bound.

A partial index on ``(lease_expires_at)`` filtered to ``status = 'running'``
keeps the reclaim scan (the only query on these columns) cheap without
bloating the index with terminal/pending rows.

Revision ID: 20260702_000003
Revises: 20260702_000002
Create Date: 2026-07-02 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260702_000003"
down_revision: Union[str, None] = "20260702_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_tasks", sa.Column("owner_instance_id", sa.Text(), nullable=True))
    op.add_column(
        "joysafeter_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_ct_running_lease",
        "joysafeter_tasks",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("idx_ct_running_lease", table_name="joysafeter_tasks")
    op.drop_column("joysafeter_tasks", "lease_expires_at")
    op.drop_column("joysafeter_tasks", "owner_instance_id")
