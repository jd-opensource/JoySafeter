"""Separate desired and applied sandbox network-policy generations.

Revision ID: 20260824_000002
Revises: 20260824_000001
Create Date: 2026-08-24 00:00:02.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_000002"
down_revision: Union[str, None] = "20260824_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

READY_GENERATION_CONSTRAINT = "ck_sandbox_ready_network_policy_generation"


def upgrade() -> None:
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_applied_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_applied_version", sa.BigInteger(), nullable=True),
    )
    op.execute(
        """
        UPDATE joysafeter_sandboxes
        SET networking_applied_hash = networking_policy_hash,
            networking_applied_version = networking_policy_version
        WHERE networking_status = 'ready'
        """
    )
    op.create_check_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        "networking_status <> 'ready' OR "
        "(networking_applied_hash IS NOT DISTINCT FROM networking_policy_hash "
        "AND networking_applied_version IS NOT DISTINCT FROM networking_policy_version)",
    )


def downgrade() -> None:
    op.drop_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.drop_column("joysafeter_sandboxes", "networking_applied_version")
    op.drop_column("joysafeter_sandboxes", "networking_applied_hash")
