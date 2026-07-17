"""scope secret and vault names by project

Revision ID: 20260716_000012
Revises: 20260710_000011
Create Date: 2026-07-16 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260716_000012"
down_revision: Union[str, None] = "20260710_000011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("idx_cs_name_unique", "joysafeter_secrets", type_="unique")
    op.drop_constraint("idx_cv_name", "joysafeter_vaults", type_="unique")

    op.create_index(
        "uq_joysafeter_secrets_project_name",
        "joysafeter_secrets",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_secrets_global_name",
        "joysafeter_secrets",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_vaults_project_name",
        "joysafeter_vaults",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_vaults_global_name",
        "joysafeter_vaults",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_joysafeter_vaults_global_name", table_name="joysafeter_vaults")
    op.drop_index("uq_joysafeter_vaults_project_name", table_name="joysafeter_vaults")
    op.drop_index("uq_joysafeter_secrets_global_name", table_name="joysafeter_secrets")
    op.drop_index("uq_joysafeter_secrets_project_name", table_name="joysafeter_secrets")

    op.create_unique_constraint("idx_cv_name", "joysafeter_vaults", ["name"])
    op.create_unique_constraint("idx_cs_name_unique", "joysafeter_secrets", ["name"])
