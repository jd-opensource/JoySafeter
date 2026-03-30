"""drop deprecated provider_name columns from model_instance and model_credential

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-03-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s4t5u6v7w8x9"
down_revision: Union[str, None] = "r3s4t5u6v7w8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop index on model_instance.provider_name if it exists
    op.execute("""
        DROP INDEX IF EXISTS model_instance_provider_name_idx
    """)

    # Drop provider_name column from model_instance
    op.drop_column("model_instance", "provider_name")

    # Drop index on model_credential.provider_name if it exists
    op.execute("""
        DROP INDEX IF EXISTS model_credential_provider_name_idx
    """)

    # Drop provider_name column from model_credential
    op.drop_column("model_credential", "provider_name")


def downgrade() -> None:
    # Re-add provider_name to model_credential as nullable
    op.add_column(
        "model_credential",
        sa.Column("provider_name", sa.String(100), nullable=True),
    )

    # Re-add provider_name to model_instance as nullable
    op.add_column(
        "model_instance",
        sa.Column("provider_name", sa.String(100), nullable=True),
    )
