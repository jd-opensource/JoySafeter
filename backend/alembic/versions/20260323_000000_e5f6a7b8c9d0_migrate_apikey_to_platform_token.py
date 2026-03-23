"""Migrate ApiKey system to unified PlatformToken system.

Steps:
1. Migrate existing api_key records to platform_tokens
2. Drop api_key_id FK from graph_executions
3. Drop api_key_id column from graph_executions
4. Rename api_key table to api_keys_deprecated (30-day retention)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-23 00:00:00.000000+00:00

"""

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Migrate existing api_key records to platform_tokens
    result = conn.execute(
        sa.text("""
        SELECT id, user_id, workspace_id, key, name, created_at, last_used
        FROM api_key
    """)
    )

    migrated_count = 0
    for row in result:
        token_hash = hashlib.sha256(row.key.encode()).hexdigest()
        token_prefix = row.key[:12] if len(row.key) >= 12 else row.key

        conn.execute(
            sa.text("""
            INSERT INTO platform_tokens
            (user_id, name, token_hash, token_prefix, scopes, resource_type, resource_id,
             is_active, created_at, last_used_at)
            VALUES
            (:user_id, :name, :token_hash, :token_prefix, :scopes, :resource_type, :resource_id,
             true, :created_at, :last_used_at)
        """),
            {
                "user_id": row.user_id,
                "name": row.name or "Migrated API Key",
                "token_hash": token_hash,
                "token_prefix": token_prefix,
                "scopes": ["graphs:execute"],
                "resource_type": "graph",
                "resource_id": row.workspace_id,
                "created_at": row.created_at,
                "last_used_at": row.last_used,
            },
        )
        migrated_count += 1

    print(f"Migrated {migrated_count} active API keys to platform_tokens")

    # 2. Drop FK constraint and column from graph_executions
    op.drop_constraint(
        "graph_executions_api_key_id_fkey",
        "graph_executions",
        type_="foreignkey",
    )
    op.drop_column("graph_executions", "api_key_id")

    # 3. Rename api_key table for 30-day verification period
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
