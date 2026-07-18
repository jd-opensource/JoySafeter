"""skills: add org/public version pointers + review target; drop root_path

Revision ID: 20260718_000001
Revises: 20260717_000016
Create Date: 2026-07-18 00:00:00.000000+00:00

Single-axis skills redesign, Phase 1 (additive, non-breaking):

- joysafeter_skills gains ``org_version_id`` / ``public_version_id`` — nullable
  FKs onto joysafeter_skill_versions (ondelete SET NULL). They will later point
  at the last version approved for the org / public tiers; NULL for now.
- joysafeter_skill_versions gains ``review_target_visibility`` (String(16),
  nullable) to record which visibility tier a pending review targets.
- ``root_path`` is removed from joysafeter_skills — it has always been NULL with
  no readers or writers.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260718_000001"
down_revision: Union[str, None] = "20260717_000016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_skills", sa.Column("org_version_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_skills", sa.Column("public_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_skills_org_version",
        "joysafeter_skills",
        "joysafeter_skill_versions",
        ["org_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_skills_public_version",
        "joysafeter_skills",
        "joysafeter_skill_versions",
        ["public_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "joysafeter_skill_versions",
        sa.Column("review_target_visibility", sa.String(length=16), nullable=True),
    )

    op.drop_column("joysafeter_skills", "root_path")


def downgrade() -> None:
    op.add_column(
        "joysafeter_skills",
        sa.Column("root_path", sa.String(length=512), nullable=True),
    )

    op.drop_column("joysafeter_skill_versions", "review_target_visibility")

    op.drop_constraint("fk_skills_public_version", "joysafeter_skills", type_="foreignkey")
    op.drop_constraint("fk_skills_org_version", "joysafeter_skills", type_="foreignkey")
    op.drop_column("joysafeter_skills", "public_version_id")
    op.drop_column("joysafeter_skills", "org_version_id")
