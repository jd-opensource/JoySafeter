"""Add append-only credential material access audit records.

Revision ID: 20260822_000001
Revises: 20260821_000004
Create Date: 2026-08-22 18:00:00.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_000001"
down_revision: Union[str, None] = "20260821_000004"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_credential_access_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_kind", sa.String(length=16), nullable=True),
        sa.Column("usage", sa.String(length=64), nullable=False),
        sa.Column("consumer_type", sa.String(length=64), nullable=False),
        sa.Column("consumer_id", sa.String(length=255), nullable=True),
        sa.Column("principal_type", sa.String(length=32), nullable=True),
        sa.Column("principal_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("ip_address", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.String(length=1024), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generation", sa.BigInteger(), nullable=True),
        sa.Column("field_names", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(field_names) = 'array'",
            name="credential_access_audit_field_names",
        ),
        sa.CheckConstraint(
            "generation IS NULL OR generation >= 0",
            name="credential_access_audit_generation",
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="credential_access_audit_result",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_credential_access_audits_project_created",
        "joysafeter_credential_access_audits",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_credential_access_audits_credential_created",
        "joysafeter_credential_access_audits",
        ["credential_id", "created_at"],
    )
    op.create_index(
        "ix_credential_access_audits_session_generation",
        "joysafeter_credential_access_audits",
        ["session_id", "generation"],
    )
    op.create_index(
        "ix_credential_access_audits_result_created",
        "joysafeter_credential_access_audits",
        ["result", "created_at"],
    )
    op.create_index(
        "ix_credential_access_audits_principal_created",
        "joysafeter_credential_access_audits",
        ["principal_type", "principal_id", "created_at"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_credential_access_audits_runtime_success
        ON joysafeter_credential_access_audits
            (session_id, generation, credential_id, usage, consumer_type, consumer_id)
        NULLS NOT DISTINCT
        WHERE result = 'success' AND session_id IS NOT NULL AND generation IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_credential_access_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'credential access audit rows are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER credential_access_audits_append_only
        BEFORE UPDATE OR DELETE ON joysafeter_credential_access_audits
        FOR EACH ROW EXECUTE FUNCTION prevent_credential_access_audit_mutation()
        """
    )


def downgrade() -> None:
    op.drop_table("joysafeter_credential_access_audits")
    op.execute("DROP FUNCTION prevent_credential_access_audit_mutation()")
