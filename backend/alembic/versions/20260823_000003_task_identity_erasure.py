"""Erase task identity material on terminal state or expiry.

Revision ID: 20260823_000003
Revises: 20260823_000002
Create Date: 2026-08-23 11:00:00.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_000003"
down_revision: Union[str, None] = "20260823_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_task_identity_contexts",
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE joysafeter_task_identity_contexts AS identity
        SET encrypted_credential = NULL,
            erased_at = COALESCE(identity.consumed_at, identity.expires_at, now()),
            updated_at = GREATEST(identity.updated_at, COALESCE(identity.consumed_at, identity.expires_at, now()))
        FROM joysafeter_tasks AS task
        WHERE task.id = identity.task_id
          AND identity.encrypted_credential IS NOT NULL
          AND (
              identity.consumed_at IS NOT NULL
              OR identity.expires_at <= now()
              OR task.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
          )
        """
    )
    op.create_index(
        "ix_task_identity_pending_expiry",
        "joysafeter_task_identity_contexts",
        ["expires_at", "task_id"],
        postgresql_where=sa.text("encrypted_credential IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION erase_task_identity_on_terminal()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN
                UPDATE joysafeter_task_identity_contexts
                SET encrypted_credential = NULL,
                    erased_at = COALESCE(erased_at, now()),
                    updated_at = now()
                WHERE task_id = NEW.id AND encrypted_credential IS NOT NULL;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER task_identity_terminal_erasure
        AFTER INSERT OR UPDATE OF status ON joysafeter_tasks
        FOR EACH ROW EXECUTE FUNCTION erase_task_identity_on_terminal()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER task_identity_terminal_erasure ON joysafeter_tasks")
    op.execute("DROP FUNCTION erase_task_identity_on_terminal()")
    op.drop_index("ix_task_identity_pending_expiry", table_name="joysafeter_task_identity_contexts")
    op.drop_column("joysafeter_task_identity_contexts", "erased_at")
