"""apply schema changes made after the initial pre-release revision

Revision ID: 20260807_000002
Revises: 20260803_000001
Create Date: 2026-08-07 20:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_000002"
down_revision: Union[str, None] = "20260803_000001"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def _upgrade_usage_id(column_name: str, prefix: str) -> None:
    prefix_length = len(prefix)
    op.execute(
        sa.text(
            f"""
DO $$
DECLARE
    current_udt_name text;
BEGIN
    IF to_regclass('public.joysafeter_skill_usage_log') IS NULL THEN
        RETURN;
    END IF;

    SELECT udt_name
    INTO current_udt_name
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_skill_usage_log'
      AND column_name = '{column_name}';

    IF current_udt_name IS NOT NULL AND current_udt_name <> 'uuid' THEN
        EXECUTE $ddl$
            ALTER TABLE joysafeter_skill_usage_log
            ALTER COLUMN {column_name} TYPE uuid
            USING CASE
                WHEN {column_name} IS NULL THEN NULL
                WHEN left({column_name}::text, {prefix_length}) = '{prefix}'
                    THEN substring({column_name}::text FROM {prefix_length + 1})::uuid
                ELSE {column_name}::text::uuid
            END
        $ddl$;
    END IF;
END
$$
"""
        )
    )


def _downgrade_usage_id(column_name: str) -> None:
    op.execute(
        sa.text(
            f"""
DO $$
DECLARE
    current_udt_name text;
    current_length integer;
BEGIN
    IF to_regclass('public.joysafeter_skill_usage_log') IS NULL THEN
        RETURN;
    END IF;

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_skill_usage_log'
      AND column_name = '{column_name}';

    IF current_udt_name IS NOT NULL
       AND (current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 255) THEN
        EXECUTE $ddl$
            ALTER TABLE joysafeter_skill_usage_log
            ALTER COLUMN {column_name} TYPE varchar(255)
            USING {column_name}::text
        $ddl$;
    END IF;
END
$$
"""
        )
    )


def _upgrade_secret_columns() -> None:
    op.execute(
        sa.text(
            """
DO $$
DECLARE
    current_udt_name text;
    current_length integer;
BEGIN
    IF to_regclass('public.joysafeter_secrets') IS NULL THEN
        RETURN;
    END IF;

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_secrets'
      AND column_name = 'kind';

    IF current_udt_name IS NULL THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ADD COLUMN kind varchar(16)';
    ELSIF current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 16 THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN kind TYPE varchar(16) USING kind::text';
    END IF;

    EXECUTE 'UPDATE joysafeter_secrets SET kind = ''llm'' WHERE kind IS NULL';
    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN kind DROP DEFAULT';
    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN kind SET NOT NULL';

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_secrets'
      AND column_name = 'provider';

    IF current_udt_name IS NULL THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ADD COLUMN provider varchar(64)';
    ELSIF current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 64 THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider TYPE varchar(64) USING provider::text';
    END IF;

    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider DROP DEFAULT';
    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider DROP NOT NULL';

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_secrets'
      AND column_name = 'protocol';

    IF current_udt_name IS NULL THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ADD COLUMN protocol varchar(64)';
    ELSIF current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 64 THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol TYPE varchar(64) USING protocol::text';
    END IF;

    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol DROP DEFAULT';
    EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol DROP NOT NULL';
END
$$
"""
        )
    )


def _upgrade_secret_objects() -> None:
    op.execute(
        sa.text(
            """
DO $$
BEGIN
    IF to_regclass('public.joysafeter_secrets') IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'joysafeter_secrets'::regclass
          AND conname = 'ck_joysafeter_secrets_kind_identity'
    ) THEN
        ALTER TABLE joysafeter_secrets
        ADD CONSTRAINT ck_joysafeter_secrets_kind_identity
        CHECK (
            (kind = 'llm' AND provider IS NOT NULL AND protocol IS NOT NULL)
            OR (kind = 'generic' AND provider IS NULL AND protocol IS NULL AND is_default = false)
        );
    END IF;

    WITH ranked_defaults AS (
        SELECT
            id,
            row_number() OVER (
                PARTITION BY project_id, protocol
                ORDER BY updated_at DESC, id DESC
            ) AS default_rank
        FROM joysafeter_secrets
        WHERE kind = 'llm'
          AND is_default = true
          AND deleted_at IS NULL
    )
    UPDATE joysafeter_secrets AS secret
    SET is_default = false
    FROM ranked_defaults
    WHERE secret.id = ranked_defaults.id
      AND ranked_defaults.default_rank > 1;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_joysafeter_secrets_global_protocol_default
        ON joysafeter_secrets (protocol)
        WHERE project_id IS NULL
          AND kind = 'llm'
          AND is_default = true
          AND deleted_at IS NULL;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_joysafeter_secrets_project_protocol_default
        ON joysafeter_secrets (project_id, protocol)
        WHERE project_id IS NOT NULL
          AND kind = 'llm'
          AND is_default = true
          AND deleted_at IS NULL;
END
$$
"""
        )
    )


def _downgrade_secret_schema() -> None:
    op.execute(
        sa.text(
            """
DO $$
DECLARE
    current_udt_name text;
    current_length integer;
BEGIN
    IF to_regclass('public.joysafeter_secrets') IS NULL THEN
        RETURN;
    END IF;

    DROP INDEX IF EXISTS uq_joysafeter_secrets_project_protocol_default;
    DROP INDEX IF EXISTS uq_joysafeter_secrets_global_protocol_default;
    ALTER TABLE joysafeter_secrets
        DROP CONSTRAINT IF EXISTS ck_joysafeter_secrets_kind_identity;

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_secrets'
      AND column_name = 'provider';

    IF current_udt_name IS NOT NULL THEN
        IF current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 64 THEN
            EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider TYPE varchar(64) USING provider::text';
        END IF;
        EXECUTE 'UPDATE joysafeter_secrets SET provider = ''custom'' WHERE provider IS NULL';
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider SET DEFAULT ''custom''';
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN provider SET NOT NULL';
    END IF;

    SELECT udt_name, character_maximum_length
    INTO current_udt_name, current_length
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'joysafeter_secrets'
      AND column_name = 'protocol';

    IF current_udt_name IS NOT NULL THEN
        IF current_udt_name <> 'varchar' OR current_length IS DISTINCT FROM 64 THEN
            EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol TYPE varchar(64) USING protocol::text';
        END IF;
        EXECUTE 'UPDATE joysafeter_secrets SET protocol = ''custom'' WHERE protocol IS NULL';
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol SET DEFAULT ''custom''';
        EXECUTE 'ALTER TABLE joysafeter_secrets ALTER COLUMN protocol SET NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'joysafeter_secrets'
          AND column_name = 'kind'
    ) THEN
        EXECUTE 'ALTER TABLE joysafeter_secrets DROP COLUMN kind';
    END IF;
END
$$
"""
        )
    )


def upgrade() -> None:
    _upgrade_usage_id("session_id", "sess_")
    _upgrade_usage_id("agent_id", "agent_")
    _upgrade_secret_columns()
    _upgrade_secret_objects()


def downgrade() -> None:
    _downgrade_secret_schema()
    _downgrade_usage_id("agent_id")
    _downgrade_usage_id("session_id")
