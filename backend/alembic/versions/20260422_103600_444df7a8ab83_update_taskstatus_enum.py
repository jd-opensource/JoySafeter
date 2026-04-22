"""update taskstatus enum

Revision ID: 444df7a8ab83
Revises: 333df7a8ab82
Create Date: 2026-04-22 10:36:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '444df7a8ab83'
down_revision: Union[str, None] = '333df7a8ab82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename 'needs_review' to 'in_review'
    op.execute("ALTER TYPE taskstatus RENAME VALUE 'needs_review' TO 'in_review';")
    # Add 'todo' to taskstatus
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'todo';")


def downgrade() -> None:
    # Rename 'in_review' back to 'needs_review'
    op.execute("ALTER TYPE taskstatus RENAME VALUE 'in_review' TO 'needs_review';")
    # Note: PostgreSQL does not support dropping an enum value without recreating the type.
    # We will leave 'todo' in the enum type during downgrade.
