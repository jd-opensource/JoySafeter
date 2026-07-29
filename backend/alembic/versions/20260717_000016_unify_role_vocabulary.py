"""unify role vocabulary across org / api-key / skill-collaborator

Revision ID: 20260717_000016
Revises: 20260717_000015
Create Date: 2026-07-17

Completes the role/permission naming unification:

- Organization members collapse to the 3-tier org vocabulary
  (owner/admin/member): legacy developer/viewer fold into member.
- API-key roles move onto the project capability vocabulary
  (admin/editor/viewer): legacy owner->admin, developer/member->editor.
- Skill-collaborator roles drop the bespoke ``collaborator_role`` Postgres
  enum in favour of a plain varchar (consistent with every other role column),
  folding the legacy ``publisher`` tier into ``admin``.

Project-member roles were already normalized by 20260717_000014.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260717_000016"
down_revision: Union[str, None] = "20260717_000015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Org members: developer/viewer no longer carry capability at the org layer.
    op.execute("UPDATE joysafeter_organization_members SET role = 'member' WHERE role IN ('developer', 'viewer')")

    # API keys: reinterpret the stored role in the project capability vocabulary.
    op.execute("UPDATE joysafeter_api_keys SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE joysafeter_api_keys SET role = 'editor' WHERE role IN ('developer', 'member')")

    # Skill collaborators: drop the dedicated enum type in favour of varchar and
    # fold publisher into admin. Convert the column first so DROP TYPE is safe.
    op.execute("ALTER TABLE joysafeter_skill_collaborators ALTER COLUMN role TYPE varchar(50) USING role::text")
    op.execute("UPDATE joysafeter_skill_collaborators SET role = 'admin' WHERE role = 'publisher'")
    op.execute("DROP TYPE IF EXISTS collaborator_role")


def downgrade() -> None:
    # Best-effort inverse. The org/api-key folds are lossy (member could have been
    # developer or viewer; editor could have been developer or member), so we only
    # restore the vocabulary shape, not the original values.
    op.execute("UPDATE joysafeter_api_keys SET role = 'developer' WHERE role = 'editor'")

    op.execute("CREATE TYPE collaborator_role AS ENUM ('viewer', 'editor', 'publisher', 'admin')")
    op.execute(
        "ALTER TABLE joysafeter_skill_collaborators "
        "ALTER COLUMN role TYPE collaborator_role USING role::collaborator_role"
    )
