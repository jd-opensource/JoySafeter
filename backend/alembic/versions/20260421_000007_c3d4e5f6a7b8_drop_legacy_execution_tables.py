"""drop legacy execution tables"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"


def upgrade():
    # Drop tables in dependency order
    # 1. Drop snapshot tables first (they depend on main tables)
    try:
        op.drop_table("execution_snapshots")
    except Exception:
        pass

    try:
        op.drop_table("agent_run_snapshots")
    except Exception:
        pass

    # 2. Drop event tables
    op.drop_table("execution_events")
    op.drop_table("agent_run_events")

    # 3. Remove FK from missions table
    try:
        op.drop_constraint("fk_missions_current_execution", "missions", type_="foreignkey")
    except Exception:
        pass

    try:
        op.drop_column("missions", "current_execution_id")
    except Exception:
        pass

    # 4. Drop main tables
    op.drop_table("executions")
    op.drop_table("agent_runs")


def downgrade():
    pass
