"""Add FK constraint on missions.current_execution_id -> executions.id"""

from typing import Union

from alembic import op

revision: str = "f8f7f6f5f4f3"
down_revision: Union[str, None] = "e7e6e5e4e3e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE missions
        SET current_execution_id = NULL
        WHERE current_execution_id IS NOT NULL
          AND current_execution_id NOT IN (SELECT id FROM executions)
    """)
    op.create_foreign_key(
        "fk_missions_current_execution_id",
        "missions",
        "executions",
        ["current_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_missions_current_execution_id", "missions", type_="foreignkey")
