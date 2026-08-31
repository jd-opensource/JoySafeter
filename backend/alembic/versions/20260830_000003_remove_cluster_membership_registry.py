"""Remove the legacy PostgreSQL cluster membership registry.

Revision ID: 20260830_000003
Revises: 20260830_000002
Create Date: 2026-08-30 00:00:03.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260830_000003"
down_revision: Union[str, None] = "20260830_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.drop_table("joysafeter_cluster_members")


def downgrade() -> None:
    op.create_table(
        "joysafeter_cluster_members",
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("instance_id", name=op.f("pk_joysafeter_cluster_members")),
    )
    op.create_index(
        "idx_joysafeter_cluster_members_role_expires_at",
        "joysafeter_cluster_members",
        ["role", "expires_at"],
    )
