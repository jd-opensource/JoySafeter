"""update_skills_agent_skills_spec

Revision ID: 000000000002
Revises: 000000000001
Create Date: 2026-01-08 00:00:02.000000+00:00

Update skills table to comply with Agent Skills specification:
- Change name from String(255) to String(64)
- Change description from Text to String(1024)
- Add compatibility field (String(500), nullable)
- Add metadata field (JSONB, default={})
- Add allowed_tools field (JSONB, default=[])
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000002"
down_revision: Union[str, None] = "000000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add new columns (nullable first, then we'll backfill)
    # Use DO block to check and add columns safely
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'compatibility'
            ) THEN
                ALTER TABLE skills ADD COLUMN compatibility VARCHAR(500);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'metadata'
            ) THEN
                ALTER TABLE skills ADD COLUMN metadata JSONB;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'allowed_tools'
            ) THEN
                ALTER TABLE skills ADD COLUMN allowed_tools JSONB;
            END IF;
        END $$;
    """)

    # Step 2: Set default values for new columns
    op.execute("UPDATE skills SET metadata = '{}'::jsonb WHERE metadata IS NULL")
    op.execute("UPDATE skills SET allowed_tools = '[]'::jsonb WHERE allowed_tools IS NULL")

    # Step 3: Make new columns NOT NULL with defaults (only if they're still nullable)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills'
                AND column_name = 'metadata'
                AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE skills
                ALTER COLUMN metadata SET NOT NULL,
                ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills'
                AND column_name = 'allowed_tools'
                AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE skills
                ALTER COLUMN allowed_tools SET NOT NULL,
                ALTER COLUMN allowed_tools SET DEFAULT '[]'::jsonb;
            END IF;
        END $$;
    """)

    # Step 4: Truncate name and description if they exceed new limits
    # This is safe because we're only truncating, not removing data
    op.execute("""
        UPDATE skills
        SET name = LEFT(name, 64)
        WHERE LENGTH(name) > 64
    """)
    op.execute("""
        UPDATE skills
        SET description = LEFT(description, 1024)
        WHERE LENGTH(description) > 1024
    """)

    # Step 5: Change column types
    # For name: String(255) -> String(64)
    op.alter_column("skills", "name", existing_type=sa.String(255), type_=sa.String(64), existing_nullable=False)

    # For description: Text -> String(1024)
    # First convert to VARCHAR(1024), then we can change the type
    op.execute("""
        ALTER TABLE skills
        ALTER COLUMN description TYPE VARCHAR(1024)
        USING LEFT(description, 1024)
    """)


def downgrade() -> None:
    # Revert column types (only if they exist and have the new types)
    op.execute("""
        DO $$
        BEGIN
            -- Check if name column exists and is VARCHAR(64)
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills'
                AND column_name = 'name'
                AND character_maximum_length = 64
            ) THEN
                ALTER TABLE skills ALTER COLUMN name TYPE VARCHAR(255);
            END IF;

            -- Check if description column exists and is VARCHAR(1024)
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills'
                AND column_name = 'description'
                AND character_maximum_length = 1024
            ) THEN
                ALTER TABLE skills ALTER COLUMN description TYPE TEXT;
            END IF;
        END $$;
    """)

    # Remove new columns (only if they exist)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'allowed_tools'
            ) THEN
                ALTER TABLE skills DROP COLUMN allowed_tools;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'metadata'
            ) THEN
                ALTER TABLE skills DROP COLUMN metadata;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'skills' AND column_name = 'compatibility'
            ) THEN
                ALTER TABLE skills DROP COLUMN compatibility;
            END IF;
        END $$;
    """)
