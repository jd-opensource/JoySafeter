"""normalize project member roles to admin/editor/viewer

Revision ID: 20260717_000014
Revises: 20260716_000013
Create Date: 2026-07-17

Collapses the legacy free-form ProjectMember.role vocabulary (owner/member/
developer) onto the project-role vocabulary the permission model now enforces:
owner -> admin, member/developer -> editor, viewer stays viewer. admin/editor
are left untouched. Existing rows written before the GitHub-model refactor keep
working under effective_project_capability without manual re-granting.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260717_000014"
down_revision: Union[str, None] = "20260716_000013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE joysafeter_project_members SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE joysafeter_project_members SET role = 'editor' WHERE role IN ('member', 'developer')")


def downgrade() -> None:
    # Best-effort inverse: editor came from either member or developer; we cannot
    # distinguish, so map editor -> member and admin -> owner. This is lossy but
    # restores the pre-refactor vocabulary shape.
    op.execute("UPDATE joysafeter_project_members SET role = 'owner' WHERE role = 'admin'")
    op.execute("UPDATE joysafeter_project_members SET role = 'member' WHERE role = 'editor'")
