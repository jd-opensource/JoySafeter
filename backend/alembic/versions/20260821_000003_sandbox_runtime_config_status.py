"""Persist sandbox runtime configuration freshness.

Revision ID: 20260821_000003
Revises: 20260821_000002
Create Date: 2026-08-21 16:00:00.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_000003"
down_revision: Union[str, None] = "20260821_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column(
            "runtime_config_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ready'"),
        ),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("runtime_config_last_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("runtime_config_required_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_joysafeter_sandboxes_runtime_config_status",
        "joysafeter_sandboxes",
        "runtime_config_status IN ('ready', 'restart_required')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_joysafeter_sandboxes_runtime_config_status",
        "joysafeter_sandboxes",
        type_="check",
    )
    op.drop_column("joysafeter_sandboxes", "runtime_config_required_at")
    op.drop_column("joysafeter_sandboxes", "runtime_config_last_reason")
    op.drop_column("joysafeter_sandboxes", "runtime_config_status")
