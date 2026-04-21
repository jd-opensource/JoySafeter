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
    op.drop_index("executions_agent_profile_idx", table_name="executions")
    op.drop_constraint(
        "executions_agent_profile_id_fkey", "executions", type_="foreignkey"
    )
    op.drop_table("agent_profiles")


def downgrade():
    pass  # no data migration, no rollback
