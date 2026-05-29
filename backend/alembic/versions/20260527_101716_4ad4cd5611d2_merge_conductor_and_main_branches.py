"""merge conductor and main branches

Revision ID: 4ad4cd5611d2
Revises: e5d14297a8c9, g1g2g3g4g5g6
Create Date: 2026-05-27 10:17:16.638944+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ad4cd5611d2'
down_revision: Union[str, None] = ('e5d14297a8c9', 'g1g2g3g4g5g6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
