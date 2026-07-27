"""scope skill names by project

Skill names move from a per-owner identity key ``(owner_id, name)`` to a
per-project key ``(project_id, name)`` — the single-axis model, matching how
agents / environments / secrets / vaults are already scoped. ``owner_id`` stays
on the row (attribution + ownership-transfer principal) but is no longer part of
the uniqueness key. ``project_id`` is already NOT NULL and skills are hard-
deleted (no ``deleted_at``), so a plain unique constraint suffices — no partial
index / global carve-out like the agent/environment migration needed.

Revision ID: 20260727_000001
Revises: 20260724_000001
Create Date: 2026-07-27 00:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260727_000001"
down_revision: Union[str, None] = "20260724_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("skills_owner_name_unique", "joysafeter_skills", type_="unique")
    op.create_unique_constraint(
        "skills_project_name_unique",
        "joysafeter_skills",
        ["project_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("skills_project_name_unique", "joysafeter_skills", type_="unique")
    op.create_unique_constraint(
        "skills_owner_name_unique",
        "joysafeter_skills",
        ["owner_id", "name"],
    )
