"""Make runtime skill usage idempotent per sandbox artifact.

Revision ID: 20260830_000004
Revises: 20260830_000003
Create Date: 2026-08-30 00:00:04.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260830_000004"
down_revision: Union[str, None] = "20260830_000003"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_skill_usage_log",
        sa.Column("sandbox_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_skill_usage_log_sandbox_artifact",
        "joysafeter_skill_usage_log",
        ["sandbox_id", "skill_id", "skill_version", "target", "artifact_hash"],
        unique=True,
        postgresql_where=sa.text("sandbox_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_skill_usage_log_sandbox_artifact",
        table_name="joysafeter_skill_usage_log",
    )
    op.drop_column("joysafeter_skill_usage_log", "sandbox_id")
