"""drop graph_deployment_version

Revision ID: f5f6f7f8f9f0
Revises: e4e5e6e7e8e9
Create Date: 2026-04-21

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f5f6f7f8f9f0"
down_revision = "e4e5e6e7e8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS graph_deployment_version CASCADE")


def downgrade() -> None:
    pass
