"""skills single-axis teardown: drop collaborator table, is_public, private tier; project_id NOT NULL

Revision ID: 20260718_000002
Revises: 20260718_000001
Create Date: 2026-07-18 00:00:00.000000+00:00

Single-axis skills redesign, Phase 4 (breaking teardown). Skills are now plain
project resources whose write permission comes solely from the project role;
external exposure (organization / public) flows through the version-level
promotion approval. This removes the legacy owner/collaborator axis:

- drop the ``joysafeter_skill_collaborators`` table (whole collaborator ACL).
- drop ``is_public`` (+ ``skills_public_idx``) from joysafeter_skills — visibility
  is the single source of truth.
- collapse the visibility vocabulary: backfill any ``private`` rows to ``project``
  (``private`` is no longer a valid tier; the floor is ``project``).
- ``project_id`` becomes NOT NULL — a skill always belongs to a project.

There is no production data yet, so the backfills are defensive no-ops in
practice; they keep the migration correct against any dev/staging rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260718_000002"
down_revision: Union[str, None] = "20260718_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Collapse the retired ``private`` tier to the new floor before any reader
    # can trip over an unknown value.
    op.execute("UPDATE joysafeter_skills SET visibility = 'project' WHERE visibility = 'private'")

    # Drop the collaborator ACL entirely (model + routes + service are gone).
    op.drop_table("joysafeter_skill_collaborators")

    # ``is_public`` is superseded by ``visibility``.
    op.drop_index("skills_public_idx", table_name="joysafeter_skills")
    op.drop_column("joysafeter_skills", "is_public")

    # A skill always belongs to a project now.
    op.execute("DELETE FROM joysafeter_skills WHERE project_id IS NULL")
    op.alter_column("joysafeter_skills", "project_id", existing_type=sa.String(length=255), nullable=False)

    # The FK was ondelete SET NULL, which is incompatible with the column now
    # being NOT NULL (deleting a project would try to NULL a NOT NULL column).
    # Skills are owned project resources, so cascade the delete instead.
    op.drop_constraint(
        op.f("fk_joysafeter_skills_project_id_joysafeter_organization_projects"),
        "joysafeter_skills",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_skills_project_id_joysafeter_organization_projects"),
        "joysafeter_skills",
        "joysafeter_organization_projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_joysafeter_skills_project_id_joysafeter_organization_projects"),
        "joysafeter_skills",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_skills_project_id_joysafeter_organization_projects"),
        "joysafeter_skills",
        "joysafeter_organization_projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("joysafeter_skills", "project_id", existing_type=sa.String(length=255), nullable=True)

    op.add_column(
        "joysafeter_skills",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("skills_public_idx", "joysafeter_skills", ["is_public"])

    op.create_table(
        "joysafeter_skill_collaborators",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="viewer"),
        sa.Column("invited_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["joysafeter_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["joysafeter_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["joysafeter_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "user_id", name="skill_collaborators_skill_user_unique"),
    )
    op.create_index(
        "skill_collaborators_user_skill_idx",
        "joysafeter_skill_collaborators",
        ["user_id", "skill_id"],
    )
