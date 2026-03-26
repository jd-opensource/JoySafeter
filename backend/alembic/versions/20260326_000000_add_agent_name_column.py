"""add agent name column to agent runs

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-26 00:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("agent_name", sa.String(length=100), nullable=True))
    op.execute("UPDATE agent_runs SET agent_name = 'skill_creator' WHERE agent_name IS NULL")
    op.alter_column("agent_runs", "agent_name", nullable=False)
    op.create_index("agent_runs_agent_updated_idx", "agent_runs", ["agent_name", "updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("agent_runs_agent_updated_idx", table_name="agent_runs")
    op.drop_column("agent_runs", "agent_name")
