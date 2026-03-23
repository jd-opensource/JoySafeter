"""Drop api_keys_deprecated table.

The api_key table was migrated to platform_tokens and renamed to
api_keys_deprecated on 2026-03-23. This migration drops the deprecated table.

Revision ID: g7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-23 00:00:02.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "g7a8b9c0d1e2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("api_keys_deprecated")


def downgrade() -> None:
    # Cannot restore - data was already migrated to platform_tokens
    pass
