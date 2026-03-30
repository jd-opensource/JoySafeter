"""drop deprecated provider_name columns from model_instance and model_credential

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-03-30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "s4t5u6v7w8x9"
down_revision: Union[str, None] = "r3s4t5u6v7w8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop ALL indexes that reference provider_name before dropping the column
    # (includes partial unique indexes, named indexes, etc.)
    for table in ("model_instance", "model_credential"):
        op.execute(f"""
            DO $$
            DECLARE idx RECORD;
            BEGIN
                FOR idx IN
                    SELECT i.relname AS index_name
                    FROM pg_index ix
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN pg_class t ON t.oid = ix.indrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                    WHERE t.relname = '{table}' AND a.attname = 'provider_name'
                LOOP
                    EXECUTE 'DROP INDEX IF EXISTS ' || idx.index_name;
                END LOOP;
            END $$;
        """)

    # Make provider_id NOT NULL (all rows backfilled in previous migration)
    op.alter_column("model_instance", "provider_id", nullable=False)
    op.alter_column("model_credential", "provider_id", nullable=False)

    # Drop provider_name columns
    op.drop_column("model_instance", "provider_name")
    op.drop_column("model_credential", "provider_name")


def downgrade() -> None:
    # Re-add provider_name to model_credential as nullable
    op.add_column(
        "model_credential",
        sa.Column("provider_name", sa.String(100), nullable=True),
    )

    # Re-add provider_name to model_instance as nullable
    op.add_column(
        "model_instance",
        sa.Column("provider_name", sa.String(100), nullable=True),
    )
