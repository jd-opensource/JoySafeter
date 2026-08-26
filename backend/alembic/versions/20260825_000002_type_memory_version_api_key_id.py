"""Store memory-version API-key actor IDs as native UUIDs.

Revision ID: 20260825_000002
Revises: 20260825_000001
Create Date: 2026-08-25 00:00:02.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_000002"
down_revision: Union[str, None] = "20260825_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE joysafeter_memory_versions
        ALTER COLUMN api_key_id TYPE uuid
        USING CASE
            WHEN api_key_id IS NULL THEN NULL
            WHEN api_key_id ~ '^apikey_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN substring(api_key_id FROM 8)::uuid
            ELSE api_key_id::uuid
        END
        """
    )


def downgrade() -> None:
    op.alter_column(
        "joysafeter_memory_versions",
        "api_key_id",
        existing_type=sa.Uuid(),
        type_=sa.Text(),
        postgresql_using="CASE WHEN api_key_id IS NULL THEN NULL ELSE 'apikey_' || api_key_id::text END",
        existing_nullable=True,
    )
