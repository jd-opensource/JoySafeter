"""add encrypted_custom_env to agents

Revision ID: bb1cc2dd3ee4
Revises: aab1c2d3e4f5
Create Date: 2026-04-27 00:00:00.000000+00:00

Changes:
- Add encrypted_custom_env (Text, nullable) to agents table for
  per-agent API key overrides, replacing the dropped agent_profiles.custom_env.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bb1cc2dd3ee4"
down_revision: Union[str, None] = "aab1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("encrypted_custom_env", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "encrypted_custom_env")
