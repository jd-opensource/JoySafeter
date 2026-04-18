"""Drop redundant source_id column from executions table."""

from typing import Union

from alembic import op

revision: str = "a9a8a7a6a5a4"
down_revision: Union[str, None] = "f8f7f6f5f4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("executions", "source_id")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("executions", sa.Column("source_id", sa.String(255), nullable=True))
