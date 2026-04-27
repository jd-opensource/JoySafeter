"""drop legacy execution tables"""

from alembic import op

revision = "cc33dd44ee55"
down_revision = "bb22cc33dd44"


def upgrade():
    # Use SQL-level IF EXISTS / CASCADE — Python try/except won't work
    # because a failed statement aborts the entire PostgreSQL transaction.

    # 1. Drop snapshot tables first (they depend on main tables)
    op.execute("DROP TABLE IF EXISTS execution_snapshots")
    op.execute("DROP TABLE IF EXISTS agent_run_snapshots")

    # 2. Drop event tables
    op.execute("DROP TABLE IF EXISTS execution_events CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_run_events CASCADE")

    # 3. Remove FK from missions table
    op.execute("ALTER TABLE missions DROP CONSTRAINT IF EXISTS fk_missions_current_execution")
    op.execute("ALTER TABLE missions DROP COLUMN IF EXISTS current_execution_id")

    # 4. Drop main tables (CASCADE handles any remaining dependent FKs)
    op.execute("DROP TABLE IF EXISTS executions CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_runs CASCADE")


def downgrade():
    pass
