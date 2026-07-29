"""add durable cluster member heartbeat mirror

Mirrors runtime instance liveness into Postgres so production recovery and
Game Day checks have an auditable source beyond Redis TTL keys.

Revision ID: 20260703_000009
Revises: 20260703_000008
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260703_000009"
down_revision: Union[str, None] = "20260703_000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_cluster_members",
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("instance_id", name="pk_joysafeter_cluster_members"),
    )
    op.create_index(
        "idx_joysafeter_cluster_members_role_expires_at",
        "joysafeter_cluster_members",
        ["role", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_joysafeter_cluster_members_role_expires_at", table_name="joysafeter_cluster_members")
    op.drop_table("joysafeter_cluster_members")
