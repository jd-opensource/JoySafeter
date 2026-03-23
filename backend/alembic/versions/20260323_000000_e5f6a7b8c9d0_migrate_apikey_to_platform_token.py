"""Migrate ApiKey system to unified PlatformToken system.

Steps:
1. Drop api_key_id FK from graph_executions
2. Drop api_key_id column from graph_executions
3. Rename api_key table to api_keys_deprecated (30-day retention)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-23 00:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop FK constraint and column from graph_executions
    op.drop_constraint(
        "graph_executions_api_key_id_fkey",
        "graph_executions",
        type_="foreignkey",
    )
    op.drop_column("graph_executions", "api_key_id")

    # 2. Rename api_key table for 30-day verification period
    #    Existing data is preserved; table can be dropped after 2026-04-23
    op.rename_table("api_key", "api_keys_deprecated")
    op.execute(
        "COMMENT ON TABLE api_keys_deprecated IS "
        "'Deprecated: migrated to platform_tokens. Safe to drop after 2026-04-23.'"
    )


def downgrade() -> None:
    # 1. Restore api_key table name
    op.rename_table("api_keys_deprecated", "api_key")
    op.execute("COMMENT ON TABLE api_key IS NULL")

    # 2. Re-add api_key_id column and FK to graph_executions
    op.add_column(
        "graph_executions",
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "graph_executions_api_key_id_fkey",
        "graph_executions",
        "api_key",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
