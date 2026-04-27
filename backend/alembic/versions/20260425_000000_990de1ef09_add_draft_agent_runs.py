"""add draft agent runs

Revision ID: 990de1ef09
Revises: 889cd0def08
Create Date: 2026-04-25 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "990de1ef09"
down_revision: Union[str, None] = "889cd0def08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("agent_version_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_agent_runs_agent_version_id",
        "agent_runs",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
    )
    op.alter_column("agent_runs", "release_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.create_check_constraint(
        "ck_agent_runs_release_or_version",
        "agent_runs",
        "(release_id IS NOT NULL) <> (agent_version_id IS NOT NULL)",
    )
    op.create_index(
        "ix_agent_runs_agent_version_id",
        "agent_runs",
        ["agent_version_id"],
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_runs_release_or_version", "agent_runs", type_="check")
    op.drop_index("ix_agent_runs_agent_version_id", table_name="agent_runs")
    op.execute("DELETE FROM agent_runs WHERE release_id IS NULL")
    op.alter_column("agent_runs", "release_id", existing_type=UUID(as_uuid=True), nullable=False)
    op.drop_constraint("fk_agent_runs_agent_version_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "agent_version_id")
