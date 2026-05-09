"""agent_run_unique_active_per_thread

Revision ID: e5d14297a8c9
Revises: d4c031e5f7b8
Create Date: 2026-05-09

Partial unique index that enforces "at most one active AgentRun per Thread" at
the DB level. The service-layer SELECT check in _require_no_active_run is a
fast path; this index is the correctness backstop under concurrent dispatch.
"""

from alembic import op

revision = "e5d14297a8c9"
down_revision = "d4c031e5f7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_runs_active_per_thread "
        "ON agent_runs (thread_id) "
        "WHERE status IN ('pending', 'running')"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_agent_runs_active_per_thread")
