"""Enforce API-key identity and project integrity.

Revision ID: 20260823_000001
Revises: 20260822_000001
Create Date: 2026-08-23 09:00:00.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_000001"
down_revision: Union[str, None] = "20260822_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM joysafeter_api_keys AS api_key
                JOIN joysafeter_organization_projects AS project ON project.id = api_key.project_id
                WHERE project.org_id <> api_key.org_id
            ) THEN
                RAISE EXCEPTION 'api key project/org mismatch blocks integrity migration';
            END IF;
            IF EXISTS (
                SELECT 1 FROM joysafeter_api_keys
                WHERE role NOT IN ('admin', 'editor', 'viewer')
                   OR length(btrim(name)) = 0
                   OR (expires_at IS NOT NULL AND expires_at <= created_at)
            ) THEN
                RAISE EXCEPTION 'invalid api key role/name/expiry blocks integrity migration';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        WITH duplicates AS (
            SELECT id, row_number() OVER (PARTITION BY key_hash ORDER BY created_at, id) AS ordinal
            FROM joysafeter_api_keys
        )
        UPDATE joysafeter_api_keys AS api_key
        SET revoked_at = COALESCE(api_key.revoked_at, now()),
            key_hash = api_key.key_hash || ':duplicate:' || api_key.id::text
        FROM duplicates
        WHERE duplicates.id = api_key.id AND duplicates.ordinal > 1
        """
    )
    op.drop_index("idx_cak_key_hash", table_name="joysafeter_api_keys")
    op.create_index("uq_api_keys_key_hash", "joysafeter_api_keys", ["key_hash"], unique=True)
    op.create_unique_constraint(
        "uq_joysafeter_organization_projects_id_org",
        "joysafeter_organization_projects",
        ["id", "org_id"],
    )
    op.create_foreign_key(
        "fk_api_keys_project_org",
        "joysafeter_api_keys",
        "joysafeter_organization_projects",
        ["project_id", "org_id"],
        ["id", "org_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("api_keys_role", "joysafeter_api_keys", "role IN ('admin', 'editor', 'viewer')")
    op.create_check_constraint("api_keys_name", "joysafeter_api_keys", "length(btrim(name)) > 0")
    op.create_check_constraint(
        "api_keys_expiry",
        "joysafeter_api_keys",
        "expires_at IS NULL OR expires_at > created_at",
    )
    op.create_index(
        "ix_api_keys_active_project_created_id",
        "joysafeter_api_keys",
        ["project_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_active_project_created_id", table_name="joysafeter_api_keys")
    op.drop_constraint("api_keys_expiry", "joysafeter_api_keys", type_="check")
    op.drop_constraint("api_keys_name", "joysafeter_api_keys", type_="check")
    op.drop_constraint("api_keys_role", "joysafeter_api_keys", type_="check")
    op.drop_constraint("fk_api_keys_project_org", "joysafeter_api_keys", type_="foreignkey")
    op.drop_constraint(
        "uq_joysafeter_organization_projects_id_org",
        "joysafeter_organization_projects",
        type_="unique",
    )
    op.drop_index("uq_api_keys_key_hash", table_name="joysafeter_api_keys")
    op.create_index("idx_cak_key_hash", "joysafeter_api_keys", ["key_hash"], unique=False)
