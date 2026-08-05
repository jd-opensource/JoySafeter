"""legacy head bridge before schema cleanup

Revision ID: 20260731_000003
Revises: 20260731_000002
Create Date: 2026-08-03 00:00:00.000000

Compatibility-only revision for databases that were already migrated with the
pre-squash Alembic chain. New clean deployments should not need this file.
"""

from __future__ import annotations

from typing import Union

# revision identifiers, used by Alembic.
revision: str = "20260731_000003"
down_revision: Union[str, None] = "20260731_000002"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
