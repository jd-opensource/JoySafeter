"""drop conversations table"""

from alembic import op

revision = "bb22cc33dd44"
down_revision = "aa11bb22cc33"


def upgrade():
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_messages_thread_id_conversations")
    op.drop_table("conversations")


def downgrade():
    pass
