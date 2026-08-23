"""Persist runtime configuration generations.

Revision ID: 20260821_000004
Revises: 20260821_000003
Create Date: 2026-08-21 23:00:00.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_000004"
down_revision: Union[str, None] = "20260821_000003"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_sessions",
        sa.Column(
            "runtime_config_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "joysafeter_sessions",
        sa.Column("runtime_config_generation_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sessions",
        sa.Column(
            "runtime_config_generation_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column(
            "runtime_config_applied_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sessions
            SET runtime_config_generation = 1,
                runtime_config_generation_reason = 'migration.runtime_config_generation_backfill',
                runtime_config_generation_updated_at = now()
            WHERE archived_at IS NULL
              AND status <> 'terminated'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("joysafeter_sandboxes", "runtime_config_applied_generation")
    op.drop_column("joysafeter_sessions", "runtime_config_generation_updated_at")
    op.drop_column("joysafeter_sessions", "runtime_config_generation_reason")
    op.drop_column("joysafeter_sessions", "runtime_config_generation")
