"""scope agent and environment names by project

Revision ID: 20260716_000013
Revises: 20260716_000012
Create Date: 2026-07-16 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260716_000013"
down_revision: Union[str, None] = "20260716_000012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("idx_ca_name_unique", "joysafeter_agents", type_="unique")
    op.drop_constraint(op.f("uq_joysafeter_environments_name"), "joysafeter_environments", type_="unique")

    op.create_index(
        "uq_joysafeter_agents_project_name",
        "joysafeter_agents",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_agents_global_name",
        "joysafeter_agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_environments_project_name",
        "joysafeter_environments",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_joysafeter_environments_global_name",
        "joysafeter_environments",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_joysafeter_environments_global_name", table_name="joysafeter_environments")
    op.drop_index("uq_joysafeter_environments_project_name", table_name="joysafeter_environments")
    op.drop_index("uq_joysafeter_agents_global_name", table_name="joysafeter_agents")
    op.drop_index("uq_joysafeter_agents_project_name", table_name="joysafeter_agents")

    op.create_unique_constraint(op.f("uq_joysafeter_environments_name"), "joysafeter_environments", ["name"])
    op.create_unique_constraint("idx_ca_name_unique", "joysafeter_agents", ["name"])
