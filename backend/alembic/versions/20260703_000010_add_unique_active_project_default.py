"""enforce one active default project per organization

Revision ID: 20260703_000010
Revises: 20260703_000009
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260703_000010"
down_revision: Union[str, None] = "20260703_000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked_defaults AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY org_id
                        ORDER BY created_at ASC, id ASC
                    ) AS default_rank
                FROM joysafeter_organization_projects
                WHERE is_default = TRUE
                  AND archived_at IS NULL
            )
            UPDATE joysafeter_organization_projects
            SET is_default = FALSE
            WHERE id IN (
                SELECT id
                FROM ranked_defaults
                WHERE default_rank > 1
            )
            """
        )
    )
    op.create_index(
        "uq_joysafeter_organization_projects_active_default",
        "joysafeter_organization_projects",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE AND archived_at IS NULL"),
        sqlite_where=sa.text("is_default = 1 AND archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_joysafeter_organization_projects_active_default",
        table_name="joysafeter_organization_projects",
    )
