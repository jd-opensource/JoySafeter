"""Add fail-closed Runner authentication state.

Revision ID: 20260829_000001
Revises: 20260828_000001
Create Date: 2026-08-29 00:00:01.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_000001"
down_revision: Union[str, None] = "20260828_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

AUTH_STATE_CONSTRAINT = "ck_sandbox_runner_auth_state"
AUTH_SHAPE_CONSTRAINT = "ck_sandbox_runner_auth_shape"
ACTIVE_SESSION_INDEX = "idx_csb_active_session_unique"
ACTIVE_SESSION_PREDICATE = (
    "chat_session_id IS NOT NULL AND destroyed_at IS NULL AND "
    "runner_auth_state <> 'revoked' AND status IN "
    "('creating', 'provisioning', 'idle', 'running', 'stopped', 'error')"
)
LEGACY_ACTIVE_SESSION_PREDICATE = (
    "chat_session_id IS NOT NULL AND destroyed_at IS NULL AND "
    "status IN ('creating', 'provisioning', 'idle', 'running', 'stopped', 'error')"
)


def upgrade() -> None:
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column(
            "runner_auth_state",
            sa.Text(),
            nullable=False,
            server_default="revoked",
        ),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("runner_token_digest", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("runner_auth_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sandboxes
            SET config = (
                (COALESCE(config, '{}'::jsonb) - 'runner_token')
                #- '{fingerprint,env,JOYSAFETER_RUNNER_TOKEN}'
            ) #- '{fingerprint,env,JOYSAFETER_EGRESS_PROXY_TOKEN}'
            WHERE config ? 'runner_token'
               OR config #> '{fingerprint,env}' ? 'JOYSAFETER_RUNNER_TOKEN'
               OR config #> '{fingerprint,env}' ? 'JOYSAFETER_EGRESS_PROXY_TOKEN'
            """
        )
    )
    op.drop_index(ACTIVE_SESSION_INDEX, table_name="joysafeter_sandboxes")
    op.create_index(
        ACTIVE_SESSION_INDEX,
        "joysafeter_sandboxes",
        ["chat_session_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_SESSION_PREDICATE),
    )
    op.create_check_constraint(
        AUTH_STATE_CONSTRAINT,
        "joysafeter_sandboxes",
        "runner_auth_state IN ('admission', 'active', 'revoked')",
    )
    op.create_check_constraint(
        AUTH_SHAPE_CONSTRAINT,
        "joysafeter_sandboxes",
        "(runner_auth_state = 'admission' "
        "AND runner_token_digest ~ '^[0-9a-f]{64}$' "
        "AND runner_auth_expires_at IS NOT NULL) OR "
        "(runner_auth_state = 'active' "
        "AND runner_token_digest ~ '^[0-9a-f]{64}$' "
        "AND runner_auth_expires_at IS NULL) OR "
        "(runner_auth_state = 'revoked' "
        "AND runner_token_digest IS NULL "
        "AND runner_auth_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM joysafeter_sandboxes
                    WHERE runner_auth_state IN ('admission', 'active')
                      AND destroyed_at IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'cannot downgrade runner auth state while live digest-only credentials exist; revoke or destroy those sandboxes first';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sandboxes
            SET status = 'destroyed',
                destroyed_at = COALESCE(destroyed_at, NOW()),
                updated_at = NOW()
            WHERE runner_auth_state = 'revoked'
              AND destroyed_at IS NULL
            """
        )
    )
    op.drop_index(ACTIVE_SESSION_INDEX, table_name="joysafeter_sandboxes")
    op.create_index(
        ACTIVE_SESSION_INDEX,
        "joysafeter_sandboxes",
        ["chat_session_id"],
        unique=True,
        postgresql_where=sa.text(LEGACY_ACTIVE_SESSION_PREDICATE),
    )
    op.drop_constraint(AUTH_SHAPE_CONSTRAINT, "joysafeter_sandboxes", type_="check")
    op.drop_constraint(AUTH_STATE_CONSTRAINT, "joysafeter_sandboxes", type_="check")
    op.drop_column("joysafeter_sandboxes", "runner_auth_expires_at")
    op.drop_column("joysafeter_sandboxes", "runner_token_digest")
    op.drop_column("joysafeter_sandboxes", "runner_auth_state")
