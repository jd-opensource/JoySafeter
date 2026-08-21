"""Add organization project policy and project creator provenance.

Revision ID: 20260821_000001
Revises: 20260815_000002
Create Date: 2026-08-21 00:00:01.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_000001"
down_revision: Union[str, None] = "20260815_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_organizations",
        sa.Column("project_creation_policy", sa.String(length=32), server_default="admins_only", nullable=False),
    )
    op.add_column(
        "joysafeter_organization_projects",
        sa.Column("created_by_user_id", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_created_by_user",
        "joysafeter_organization_projects",
        "joysafeter_users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_joysafeter_organization_projects_created_by_user_id",
        "joysafeter_organization_projects",
        ["created_by_user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "DELETE FROM joysafeter_project_members AS pm "
            "USING joysafeter_organization_projects AS p, joysafeter_organization_members AS m "
            "WHERE pm.project_id = p.id "
            "AND pm.user_id = m.user_id "
            "AND p.org_id = m.organization_id "
            "AND (m.role IN ('owner', 'admin') OR (p.is_default IS TRUE AND pm.role = 'viewer'))"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_joysafeter_organization_projects_created_by_user_id",
        table_name="joysafeter_organization_projects",
    )
    op.drop_constraint(
        "fk_projects_created_by_user",
        "joysafeter_organization_projects",
        type_="foreignkey",
    )
    op.drop_column("joysafeter_organization_projects", "created_by_user_id")
    op.drop_column("joysafeter_organizations", "project_creation_policy")
