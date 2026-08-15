"""Add task-scoped agent identity context storage.

Revision ID: 20260814_000002
Revises: 20260814_000001
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_000002"
down_revision: Union[str, None] = "20260814_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_task_identity_contexts",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_name", sa.Text(), nullable=True),
        sa.Column("credential_kind", sa.String(length=32), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("encrypted_credential", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "credential_kind IN ('auth_code', 'identity_token')",
            name="ck_task_identity_credential_kind",
        ),
        sa.CheckConstraint(
            "(credential_kind = 'auth_code' AND credential_fingerprint IS NOT NULL) "
            "OR (credential_kind = 'identity_token' AND credential_fingerprint IS NULL)",
            name="ck_task_identity_fingerprint_kind",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["joysafeter_tasks.id"],
            name=op.f("fk_joysafeter_task_identity_contexts_task_id_joysafeter_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_joysafeter_task_identity_contexts")),
    )
    op.create_index(
        "ix_task_identity_project_expires",
        "joysafeter_task_identity_contexts",
        ["project_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_identity_user",
        "joysafeter_task_identity_contexts",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_task_identity_auth_code_fingerprint",
        "joysafeter_task_identity_contexts",
        ["credential_fingerprint"],
        unique=True,
        postgresql_where=sa.text("credential_kind = 'auth_code'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_task_identity_auth_code_fingerprint",
        table_name="joysafeter_task_identity_contexts",
    )
    op.drop_index("ix_task_identity_user", table_name="joysafeter_task_identity_contexts")
    op.drop_index(
        "ix_task_identity_project_expires",
        table_name="joysafeter_task_identity_contexts",
    )
    op.drop_table("joysafeter_task_identity_contexts")
