"""repair joysafeter_secrets schema for pre-squash local databases

Revision ID: 20260707_000001
Revises: 20260627_000001
Create Date: 2026-07-07 00:00:01.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260707_000001"
down_revision: Union[str, None] = "20260627_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Some local databases were stamped at the squashed initial revision while
    # still carrying an older secrets table. Keep this migration idempotent so
    # it is safe for both repaired local DBs and fresh deployments.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_secrets (
            project_id VARCHAR(255),
            name TEXT NOT NULL,
            provider VARCHAR(64) NOT NULL DEFAULT 'custom',
            protocol VARCHAR(64) NOT NULL DEFAULT 'custom',
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_default BOOLEAN NOT NULL DEFAULT false,
            deleted_at TIMESTAMPTZ,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS project_id VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS provider VARCHAR(64)")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS protocol VARCHAR(64)")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS data JSONB")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS is_default BOOLEAN")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
    op.execute("ALTER TABLE joysafeter_secrets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

    op.execute("UPDATE joysafeter_secrets SET provider = 'custom' WHERE provider IS NULL")
    op.execute("UPDATE joysafeter_secrets SET protocol = 'custom' WHERE protocol IS NULL")
    op.execute("UPDATE joysafeter_secrets SET data = '{}'::jsonb WHERE data IS NULL")
    op.execute("UPDATE joysafeter_secrets SET is_default = false WHERE is_default IS NULL")
    op.execute("UPDATE joysafeter_secrets SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE joysafeter_secrets SET updated_at = now() WHERE updated_at IS NULL")

    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN provider SET DEFAULT 'custom'")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN provider SET NOT NULL")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN protocol SET DEFAULT 'custom'")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN protocol SET NOT NULL")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN data SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN data SET NOT NULL")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN is_default SET DEFAULT false")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN is_default SET NOT NULL")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN updated_at SET DEFAULT now()")
    op.execute("ALTER TABLE joysafeter_secrets ALTER COLUMN updated_at SET NOT NULL")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_secrets_project_id_joysafeter_organization_projects'
            ) THEN
                ALTER TABLE joysafeter_secrets
                ADD CONSTRAINT fk_joysafeter_secrets_project_id_joysafeter_organization_projects
                FOREIGN KEY (project_id) REFERENCES joysafeter_organization_projects(id);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cs_name_unique ON joysafeter_secrets (name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_joysafeter_secrets_project_id ON joysafeter_secrets (project_id)"
    )


def downgrade() -> None:
    # Intentionally no-op: this is a forward-only local schema repair.
    pass
