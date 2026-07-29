"""repair session resource tables for pre-squash local databases

Revision ID: 20260709_000001
Revises: 20260707_000003
Create Date: 2026-07-09 00:00:01.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260709_000001"
down_revision: Union[str, None] = "20260707_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older local databases can be stamped at the squashed initial revision
    # while missing session resource tables added before the squash. Session
    # detail and quickstart resource loading depend on these tables existing.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_session_repos (
            id UUID NOT NULL PRIMARY KEY,
            session_id UUID NOT NULL,
            url TEXT NOT NULL,
            branch VARCHAR(255) NOT NULL DEFAULT '',
            mount_path TEXT NOT NULL,
            mount_name VARCHAR(255) NOT NULL DEFAULT '',
            encrypted_token TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS id UUID")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS session_id UUID")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS url TEXT")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS branch VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS mount_path TEXT")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS mount_name VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS encrypted_token TEXT")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
    op.execute("ALTER TABLE joysafeter_session_repos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
    op.execute("UPDATE joysafeter_session_repos SET branch = '' WHERE branch IS NULL")
    op.execute("UPDATE joysafeter_session_repos SET mount_name = '' WHERE mount_name IS NULL")
    op.execute("UPDATE joysafeter_session_repos SET encrypted_token = '' WHERE encrypted_token IS NULL")
    op.execute("UPDATE joysafeter_session_repos SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE joysafeter_session_repos SET updated_at = now() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE joysafeter_session_repos ALTER COLUMN branch SET DEFAULT ''")
    op.execute("ALTER TABLE joysafeter_session_repos ALTER COLUMN mount_name SET DEFAULT ''")
    op.execute("ALTER TABLE joysafeter_session_repos ALTER COLUMN encrypted_token SET DEFAULT ''")
    op.execute("ALTER TABLE joysafeter_session_repos ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE joysafeter_session_repos ALTER COLUMN updated_at SET DEFAULT now()")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_session_files (
            id UUID NOT NULL PRIMARY KEY,
            session_id UUID NOT NULL,
            file_id UUID NOT NULL,
            mount_path TEXT NOT NULL,
            access VARCHAR(20) NOT NULL DEFAULT 'read_only',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS id UUID")
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS session_id UUID")
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS file_id UUID")
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS mount_path TEXT")
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS access VARCHAR(20)")
    op.execute("ALTER TABLE joysafeter_session_files ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
    op.execute("UPDATE joysafeter_session_files SET access = 'read_only' WHERE access IS NULL")
    op.execute("UPDATE joysafeter_session_files SET created_at = now() WHERE created_at IS NULL")
    op.execute("ALTER TABLE joysafeter_session_files ALTER COLUMN access SET DEFAULT 'read_only'")
    op.execute("ALTER TABLE joysafeter_session_files ALTER COLUMN created_at SET DEFAULT now()")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_session_repos_session_id_joysafeter_sessions'
            ) THEN
                ALTER TABLE joysafeter_session_repos
                ADD CONSTRAINT fk_joysafeter_session_repos_session_id_joysafeter_sessions
                FOREIGN KEY (session_id)
                REFERENCES joysafeter_sessions(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_session_files_session_id_joysafeter_sessions'
            ) THEN
                ALTER TABLE joysafeter_session_files
                ADD CONSTRAINT fk_joysafeter_session_files_session_id_joysafeter_sessions
                FOREIGN KEY (session_id)
                REFERENCES joysafeter_sessions(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_session_files_file_id_joysafeter_files'
            ) THEN
                ALTER TABLE joysafeter_session_files
                ADD CONSTRAINT fk_joysafeter_session_files_file_id_joysafeter_files
                FOREIGN KEY (file_id)
                REFERENCES joysafeter_files(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_session_repos_session ON joysafeter_session_repos (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_session_files_session ON joysafeter_session_files (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_session_files_file ON joysafeter_session_files (file_id)")


def downgrade() -> None:
    # Forward-only local schema repair.
    pass
