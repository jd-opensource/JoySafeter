"""add task submitter identity user_id/org_id (Foundation 3 — tenancy)

Denormalizes the submitting user's tenant identity (user_id, org_id) onto each
task for attribution/audit and per-user admission control. Both nullable and
NOT FK-constrained so a task's audit record survives user/org deletion. A
composite index on (user_id, status) backs the per-user active-task count.

Revision ID: 20260703_000007
Revises: 20260703_000006
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260703_000007"
down_revision: Union[str, None] = "20260703_000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_tasks", sa.Column("user_id", sa.String(length=255), nullable=True))
    op.add_column("joysafeter_tasks", sa.Column("org_id", sa.String(length=255), nullable=True))
    op.create_index("idx_ct_user_status", "joysafeter_tasks", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_ct_user_status", table_name="joysafeter_tasks")
    op.drop_column("joysafeter_tasks", "org_id")
    op.drop_column("joysafeter_tasks", "user_id")
