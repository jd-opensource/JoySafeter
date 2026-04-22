"""drop conversations table"""
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"


def upgrade():
    op.drop_table("conversations")


def downgrade():
    pass
