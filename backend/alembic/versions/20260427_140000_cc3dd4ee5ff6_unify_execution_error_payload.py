"""unify execution error payload"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "cc3dd4ee5ff6"
down_revision = "bb1cc2dd3ee4"


def upgrade():
    op.add_column("executions", sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute(
        """
        UPDATE executions
        SET error = jsonb_build_object(
            'code', COALESCE(error_code, 'EXECUTION_FAILED'),
            'message', COALESCE(error_message, 'Execution failed'),
            'data', NULL
        )
        WHERE error_code IS NOT NULL OR error_message IS NOT NULL
        """
    )
    op.drop_column("executions", "error_code")
    op.drop_column("executions", "error_message")


def downgrade():
    op.add_column("executions", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("executions", sa.Column("error_code", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE executions
        SET error_code = error->>'code',
            error_message = error->>'message'
        WHERE error IS NOT NULL
        """
    )
    op.drop_column("executions", "error")
