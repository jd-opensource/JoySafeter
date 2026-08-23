"""Add credential encryption key canaries.

Revision ID: 20260823_000005
Revises: 20260823_000004
Create Date: 2026-08-23 00:00:05.000000
"""

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_000005"
down_revision: Union[str, None] = "20260823_000004"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_credential_encryption_canaries",
        sa.Column("key_id", sa.String(length=128), nullable=False),
        sa.Column("encrypted_canary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key_id", name="pk_joysafeter_credential_encryption_canaries"),
        sa.CheckConstraint(
            "key_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'",
            name="key_id_format",
        ),
        sa.CheckConstraint(
            "left(encrypted_canary, length('enc:v2:' || key_id || ':')) = "
            "'enc:v2:' || key_id || ':' AND "
            "length(encrypted_canary) > length('enc:v2:' || key_id || ':')",
            name="envelope_matches_key_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("joysafeter_credential_encryption_canaries")
