"""add runtime ownership columns to agent runs

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-25 18:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("runtime_owner_id", sa.String(length=255), nullable=True))
    op.add_column("agent_runs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("agent_runs_owner_status_idx", "agent_runs", ["runtime_owner_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("agent_runs_owner_status_idx", table_name="agent_runs")
    op.drop_column("agent_runs", "last_heartbeat_at")
    op.drop_column("agent_runs", "runtime_owner_id")
