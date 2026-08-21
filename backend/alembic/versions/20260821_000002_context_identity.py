"""Replace ambiguous legacy default organization and project identities.

Revision ID: 20260821_000002
Revises: 20260821_000001
Create Date: 2026-08-21 14:25:00.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_000002"
down_revision: Union[str, None] = "20260821_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE joysafeter_organizations AS organization "
            "SET name = COALESCE(NULLIF(BTRIM(owner_user.name), ''), "
            "NULLIF(SPLIT_PART(owner_user.email, '@', 1), ''), 'Personal'), "
            "slug = 'workspace-' || LEFT(REPLACE(organization.id, '-', ''), 8) "
            "FROM joysafeter_organization_members AS owner_membership "
            "JOIN joysafeter_users AS owner_user ON owner_user.id = owner_membership.user_id "
            "WHERE owner_membership.organization_id = organization.id "
            "AND owner_membership.role = 'owner' "
            "AND organization.name = 'Default' "
            "AND organization.slug = 'default'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE joysafeter_organization_projects AS project "
            "SET name = 'Main', "
            "slug = CASE "
            "WHEN EXISTS ("
            "SELECT 1 FROM joysafeter_organization_projects AS sibling "
            "WHERE sibling.org_id = project.org_id "
            "AND sibling.id <> project.id "
            "AND sibling.slug = 'main'"
            ") THEN 'main-' || LEFT(REPLACE(project.id, '-', ''), 6) "
            "ELSE 'main' END "
            "WHERE project.is_default IS TRUE "
            "AND project.name = 'Default' "
            "AND project.slug = 'default'"
        )
    )


def downgrade() -> None:
    pass
