-- Add skills table columns from migration 000000000002 (update_skills_agent_skills_spec).
-- Run this if you see: column skills.compatibility does not exist (and similar).
-- Idempotent: safe to run multiple times.
-- Alternatively, run: cd backend && alembic upgrade head

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

UPDATE skills SET metadata = '{}'::jsonb WHERE metadata IS NULL;
UPDATE skills SET allowed_tools = '[]'::jsonb WHERE allowed_tools IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'skills' AND column_name = 'metadata' AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE skills ALTER COLUMN metadata SET NOT NULL;
        ALTER TABLE skills ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'skills' AND column_name = 'allowed_tools' AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE skills ALTER COLUMN allowed_tools SET NOT NULL;
        ALTER TABLE skills ALTER COLUMN allowed_tools SET DEFAULT '[]'::jsonb;
    END IF;
END $$;
