"""Erase material from terminally deleted credentials.

Revision ID: 20260823_000002
Revises: 20260823_000001
Create Date: 2026-08-23 10:00:00.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_000002"
down_revision: Union[str, None] = "20260823_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_credentials",
        sa.Column("material_erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE joysafeter_credentials
        SET data = '{}'::jsonb,
            oauth_config = NULL,
            material_erased_at = COALESCE(deleted_at, now()),
            updated_at = GREATEST(updated_at, COALESCE(deleted_at, now()))
        WHERE deleted_at IS NOT NULL
        """
    )
    op.create_check_constraint(
        "deleted_material_erased",
        "joysafeter_credentials",
        "deleted_at IS NULL OR (material_erased_at IS NOT NULL AND data = '{}'::jsonb AND oauth_config IS NULL)",
    )
    op.create_check_constraint(
        "material_erasure_requires_delete",
        "joysafeter_credentials",
        "material_erased_at IS NULL OR deleted_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("material_erasure_requires_delete", "joysafeter_credentials", type_="check")
    op.drop_constraint("deleted_material_erased", "joysafeter_credentials", type_="check")
    op.drop_column("joysafeter_credentials", "material_erased_at")
