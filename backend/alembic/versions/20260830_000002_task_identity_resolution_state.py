"""Add fenced task identity resolution state.

Revision ID: 20260830_000002
Revises: 20260830_000001
Create Date: 2026-08-30 00:00:00.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260830_000002"
down_revision: Union[str, None] = "20260830_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_task_identity_contexts",
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'captured'"),
            nullable=False,
        ),
    )
    op.add_column(
        "joysafeter_task_identity_contexts",
        sa.Column("resolution_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "joysafeter_task_identity_contexts",
        sa.Column("resolution_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE joysafeter_task_identity_contexts AS identity
        SET state = CASE
                WHEN consumed_at IS NOT NULL THEN 'issued'
                WHEN task.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                    THEN 'discarded'
                WHEN encrypted_credential IS NULL OR expires_at <= now() THEN 'expired'
                ELSE 'captured'
            END,
            encrypted_credential = CASE
                WHEN consumed_at IS NOT NULL
                  OR task.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                  OR encrypted_credential IS NULL
                  OR expires_at <= now()
                    THEN NULL
                ELSE encrypted_credential
            END,
            erased_at = CASE
                WHEN consumed_at IS NOT NULL
                  OR task.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                  OR encrypted_credential IS NULL
                  OR expires_at <= now()
                    THEN COALESCE(erased_at, consumed_at, expires_at, now())
                ELSE NULL
            END,
            resolution_id = NULL,
            resolution_expires_at = NULL,
            updated_at = now()
        FROM joysafeter_tasks AS task
        WHERE task.id = identity.task_id
        """
    )
    op.create_check_constraint(
        "ck_task_identity_resolution_state",
        "joysafeter_task_identity_contexts",
        "state IN ('captured', 'resolving', 'issued', 'expired', 'discarded')",
    )
    op.create_check_constraint(
        "ck_task_identity_resolution_claim",
        "joysafeter_task_identity_contexts",
        "(state = 'resolving' AND resolution_id IS NOT NULL AND resolution_expires_at IS NOT NULL) "
        "OR (state <> 'resolving' AND resolution_id IS NULL AND resolution_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_task_identity_resolution_material",
        "joysafeter_task_identity_contexts",
        "(state IN ('captured', 'resolving') AND encrypted_credential IS NOT NULL "
        "AND consumed_at IS NULL AND erased_at IS NULL) "
        "OR (state = 'issued' AND encrypted_credential IS NULL "
        "AND consumed_at IS NOT NULL AND erased_at IS NOT NULL) "
        "OR (state IN ('expired', 'discarded') AND encrypted_credential IS NULL "
        "AND consumed_at IS NULL AND erased_at IS NOT NULL)",
    )
    op.create_index(
        "ix_task_identity_resolution_expiry",
        "joysafeter_task_identity_contexts",
        ["resolution_expires_at", "task_id"],
        unique=False,
        postgresql_where=sa.text("state = 'resolving'"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION erase_task_identity_on_terminal()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN
                UPDATE joysafeter_task_identity_contexts
                SET state = 'discarded',
                    encrypted_credential = NULL,
                    resolution_id = NULL,
                    resolution_expires_at = NULL,
                    erased_at = COALESCE(erased_at, now()),
                    updated_at = now()
                WHERE task_id = NEW.id
                  AND state IN ('captured', 'resolving');
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM joysafeter_task_identity_contexts
                WHERE state = 'resolving'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade task identity resolution state while active claims exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION erase_task_identity_on_terminal()
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
    op.drop_index(
        "ix_task_identity_resolution_expiry",
        table_name="joysafeter_task_identity_contexts",
    )
    op.drop_constraint(
        "ck_task_identity_resolution_material",
        "joysafeter_task_identity_contexts",
        type_="check",
    )
    op.drop_constraint(
        "ck_task_identity_resolution_claim",
        "joysafeter_task_identity_contexts",
        type_="check",
    )
    op.drop_constraint(
        "ck_task_identity_resolution_state",
        "joysafeter_task_identity_contexts",
        type_="check",
    )
    op.drop_column("joysafeter_task_identity_contexts", "resolution_expires_at")
    op.drop_column("joysafeter_task_identity_contexts", "resolution_id")
    op.drop_column("joysafeter_task_identity_contexts", "state")
