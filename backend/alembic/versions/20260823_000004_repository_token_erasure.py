"""Add repository-token expiry, rotation, and erasure lifecycle.

Revision ID: 20260823_000004
Revises: 20260823_000003
Create Date: 2026-08-23 12:00:00.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_000004"
down_revision: Union[str, None] = "20260823_000003"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_session_repos",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_session_repos",
        sa.Column("token_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_session_repos",
        sa.Column("token_erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE joysafeter_session_repos
        SET token_rotated_at = created_at
        WHERE encrypted_token <> ''
        """
    )
    op.execute(
        """
        UPDATE joysafeter_session_repos AS repo
        SET encrypted_token = '',
            token_erased_at = COALESCE(session.archived_at, session.updated_at, now()),
            updated_at = GREATEST(repo.updated_at, COALESCE(session.archived_at, session.updated_at, now()))
        FROM joysafeter_sessions AS session
        WHERE session.id = repo.session_id
          AND repo.encrypted_token <> ''
          AND (session.status = 'terminated' OR session.archived_at IS NOT NULL)
        """
    )
    op.create_check_constraint(
        "session_repo_token_erasure_consistent",
        "joysafeter_session_repos",
        "token_erased_at IS NULL OR encrypted_token = ''",
    )
    op.create_check_constraint(
        "session_repo_token_rotation_present",
        "joysafeter_session_repos",
        "encrypted_token = '' OR token_rotated_at IS NOT NULL",
    )
    op.create_index(
        "ix_session_repo_token_pending_expiry",
        "joysafeter_session_repos",
        ["token_expires_at", "id"],
        postgresql_where=sa.text("encrypted_token <> '' AND token_expires_at IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION erase_repository_tokens_on_terminal_session()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status = 'terminated' OR NEW.archived_at IS NOT NULL THEN
                UPDATE joysafeter_session_repos
                SET encrypted_token = '',
                    token_erased_at = COALESCE(token_erased_at, NEW.archived_at, now()),
                    updated_at = now()
                WHERE session_id = NEW.id AND encrypted_token <> '';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER repository_token_terminal_session_erasure
        AFTER INSERT OR UPDATE OF status, archived_at ON joysafeter_sessions
        FOR EACH ROW EXECUTE FUNCTION erase_repository_tokens_on_terminal_session()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_repository_token_session_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.encrypted_token <> '' AND EXISTS (
                SELECT 1
                FROM joysafeter_sessions AS session
                WHERE session.id = NEW.session_id
                  AND (session.status = 'terminated' OR session.archived_at IS NOT NULL)
            ) THEN
                RAISE EXCEPTION 'repository token cannot be attached to a terminal session'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.encrypted_token <> '' THEN
                NEW.token_rotated_at = COALESCE(NEW.token_rotated_at, now());
                NEW.token_erased_at = NULL;
            ELSIF TG_OP = 'UPDATE' AND OLD.encrypted_token <> '' THEN
                NEW.token_erased_at = COALESCE(NEW.token_erased_at, now());
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER repository_token_session_lifecycle_guard
        BEFORE INSERT OR UPDATE OF session_id, encrypted_token ON joysafeter_session_repos
        FOR EACH ROW EXECUTE FUNCTION enforce_repository_token_session_lifecycle()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER repository_token_session_lifecycle_guard ON joysafeter_session_repos")
    op.execute("DROP FUNCTION enforce_repository_token_session_lifecycle()")
    op.execute("DROP TRIGGER repository_token_terminal_session_erasure ON joysafeter_sessions")
    op.execute("DROP FUNCTION erase_repository_tokens_on_terminal_session()")
    op.drop_index("ix_session_repo_token_pending_expiry", table_name="joysafeter_session_repos")
    op.drop_constraint(
        "session_repo_token_rotation_present",
        "joysafeter_session_repos",
        type_="check",
    )
    op.drop_constraint(
        "session_repo_token_erasure_consistent",
        "joysafeter_session_repos",
        type_="check",
    )
    op.drop_column("joysafeter_session_repos", "token_erased_at")
    op.drop_column("joysafeter_session_repos", "token_rotated_at")
    op.drop_column("joysafeter_session_repos", "token_expires_at")
