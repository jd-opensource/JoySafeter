"""drop conversations table"""
from alembic import op

revision = "bb22cc33dd44"
down_revision = "aa11bb22cc33"


def upgrade():
    op.drop_table("conversations")


def downgrade():
    pass
