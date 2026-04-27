"""drop agent_profiles table

Revision ID: d3d4d5d6d7d8
Revises: c2c3c4c5c6c7
Create Date: 2026-04-21
"""

from alembic import op

revision = "d3d4d5d6d7d8"
down_revision = "c2c3c4c5c6c7"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the FK index on executions first, then the FK constraint,
    # before dropping the referenced table.
    # Use IF EXISTS at SQL level — Python try/except won't work because a
    # failed statement aborts the entire PostgreSQL transaction.
    op.execute("DROP INDEX IF EXISTS executions_agent_profile_idx")
    op.execute("ALTER TABLE executions DROP CONSTRAINT IF EXISTS executions_agent_profile_id_fkey")
    op.execute("ALTER TABLE executions DROP CONSTRAINT IF EXISTS fk_executions_agent_profile_id_agent_profiles")
    op.drop_table("agent_profiles")


def downgrade():
    pass  # no data migration, no rollback
