"""add todo and in_review to taskstatus enum

Revision ID: 444df7a8ab83
Revises: 333df7a8ab82
Create Date: 2026-04-22 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '444df7a8ab83'
down_revision: Union[str, None] = '333df7a8ab82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'todo'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'in_review'")


def downgrade() -> None:
    pass  # PostgreSQL cannot remove enum values
