"""merge trigger keyed and network policy migration heads

Revision ID: 20260731_000002
Revises: 20260731_000001, 20260727_000004
Create Date: 2026-07-31 18:35:00.000000

The network-policy migration branch and trigger keyed/run_at branch diverged at
20260727_000003. This merge revision makes Alembic expose a single head again.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260731_000002"
down_revision: Union[str, Sequence[str], None] = ("20260731_000001", "20260727_000004")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
