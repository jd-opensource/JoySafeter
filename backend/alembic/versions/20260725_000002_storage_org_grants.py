"""add storage organization grants

Revision ID: 20260725_000002
Revises: 20260725_000001
Create Date: 2026-07-27 00:00:01.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260725_000002"
down_revision = "20260725_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_storage_organization_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("volume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", sa.String(length=255), nullable=False),
        sa.Column("max_access", sa.String(length=16), server_default="read_only", nullable=False),
        sa.Column("allowed_prefixes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["joysafeter_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["volume_id"], ["joysafeter_storage_volumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("volume_id", "org_id", name="uq_joysafeter_storage_org_grants_volume_org"),
    )
    op.create_index("idx_joysafeter_storage_org_grants_org", "joysafeter_storage_organization_grants", ["org_id"])
    op.create_index("idx_joysafeter_storage_org_grants_volume", "joysafeter_storage_organization_grants", ["volume_id"])

    op.execute(
        """
        INSERT INTO joysafeter_storage_organization_grants (
            id, created_at, updated_at, volume_id, org_id, max_access, allowed_prefixes, quota_bytes, enabled
        )
        SELECT gen_random_uuid(), now(), now(), g.volume_id, p.org_id,
               CASE WHEN bool_and(g.max_access = 'read_only') THEN 'read_only' ELSE 'read_write' END,
               '[]'::jsonb,
               MIN(g.quota_bytes),
               true
          FROM joysafeter_storage_project_grants g
          JOIN joysafeter_organization_projects p ON p.id = g.project_id
      GROUP BY g.volume_id, p.org_id
        ON CONFLICT (volume_id, org_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_joysafeter_storage_org_grants_volume", table_name="joysafeter_storage_organization_grants")
    op.drop_index("idx_joysafeter_storage_org_grants_org", table_name="joysafeter_storage_organization_grants")
    op.drop_table("joysafeter_storage_organization_grants")
