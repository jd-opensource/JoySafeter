"""add run_id and execution_id FKs on thread_messages"""
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"


def upgrade():
    op.create_foreign_key("fk_messages_run", "thread_messages", "agent_runs", ["run_id"], ["id"])
    op.create_foreign_key("fk_messages_execution", "thread_messages", "executions", ["execution_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_messages_execution", "thread_messages", type_="foreignkey")
    op.drop_constraint("fk_messages_run", "thread_messages", type_="foreignkey")
