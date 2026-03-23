"""Drop allow_personal_api_keys column from workspace table.

This column controlled the legacy ApiKey system which has been fully
replaced by PlatformToken.  The column is no longer referenced anywhere
in the application code.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-23 00:00:01.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("workspaces", "allow_personal_api_keys")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("allow_personal_api_keys", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
