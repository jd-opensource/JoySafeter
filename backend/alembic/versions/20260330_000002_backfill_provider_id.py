"""backfill provider_id for model_instance and model_credential

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-03-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "r3s4t5u6v7w8"
down_revision: Union[str, None] = "q2r3s4t5u6v7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill provider_id for model_instance rows that only have provider_name
    op.execute("""
        UPDATE model_instance mi
        SET provider_id = mp.id
        FROM model_provider mp
        WHERE mi.provider_id IS NULL
          AND mi.provider_name IS NOT NULL
          AND mi.provider_name = mp.name
    """)

    # Backfill provider_id for model_credential rows that only have provider_name
    op.execute("""
        UPDATE model_credential mc
        SET provider_id = mp.id
        FROM model_provider mp
        WHERE mc.provider_id IS NULL
          AND mc.provider_name IS NOT NULL
          AND mc.provider_name = mp.name
    """)


def downgrade() -> None:
    # No-op: we don't remove provider_id values on downgrade
    pass
