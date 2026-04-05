"""fix_memories_table_columns

Revision ID: 000000000003
Revises: 000000000002
Create Date: 2026-01-22 00:00:03.000000+00:00

Fix missing columns in the memories table:
- Add memory column (JSON, NOT NULL)
- Add topics column (JSON, nullable)
Skip if columns already exist
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000003"
down_revision: Union[str, None] = "000000000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing memory and topics columns to the memories table"""
    # Use a DO block to safely check and add columns
    op.execute("""
        DO $$
        BEGIN
            -- Check and add the memory column
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'memory'
            ) THEN
                -- If the table has data, add as nullable first, then set defaults
                ALTER TABLE memories ADD COLUMN memory JSON;
                -- Set default value for existing rows (empty JSON object)
                UPDATE memories SET memory = '{}'::json WHERE memory IS NULL;
                -- Set to NOT NULL
                ALTER TABLE memories ALTER COLUMN memory SET NOT NULL;
            END IF;

            -- Check and add the topics column
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'topics'
            ) THEN
                ALTER TABLE memories ADD COLUMN topics JSON;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Remove memory and topics columns (only if they exist)"""
    op.execute("""
        DO $$
        BEGIN
            -- Remove topics column if it exists
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'topics'
            ) THEN
                ALTER TABLE memories DROP COLUMN topics;
            END IF;

            -- Remove memory column if it exists
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'memory'
            ) THEN
                ALTER TABLE memories DROP COLUMN memory;
            END IF;
        END $$;
    """)
