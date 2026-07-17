"""enforce one organization membership per (organization_id, user_id)

Revision ID: 20260717_000015
Revises: 20260717_000014
Create Date: 2026-07-17

The organization-members table had no uniqueness guarantee on
(organization_id, user_id), so a race between two ``add_member`` calls (which
only check-then-insert at the application layer) could create duplicate rows.
Authorization then resolves the member with ``.limit(1)`` and no ordering, so
the effective org role for a user with duplicates was nondeterministic.

This migration first de-duplicates any existing rows — keeping the row with the
highest-privilege role (tie-break: earliest created_at, then id) so no member
loses access — and then adds a unique constraint so duplicates can never recur.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_000015"
down_revision: Union[str, None] = "20260717_000014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # De-dupe: keep the highest-ranked role per (organization_id, user_id).
    op.execute(
        sa.text(
            """
            WITH ranked_members AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY organization_id, user_id
                        ORDER BY
                            CASE lower(role)
                                WHEN 'owner' THEN 4
                                WHEN 'admin' THEN 3
                                WHEN 'developer' THEN 2
                                WHEN 'member' THEN 2
                                WHEN 'viewer' THEN 1
                                ELSE 0
                            END DESC,
                            created_at ASC,
                            id ASC
                    ) AS member_rank
                FROM joysafeter_organization_members
            )
            DELETE FROM joysafeter_organization_members
            WHERE id IN (
                SELECT id FROM ranked_members WHERE member_rank > 1
            )
            """
        )
    )
    op.create_unique_constraint(
        "uq_joysafeter_organization_members_org_user",
        "joysafeter_organization_members",
        ["organization_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_joysafeter_organization_members_org_user",
        "joysafeter_organization_members",
        type_="unique",
    )
