"""add_observation_version_and_status

Revision ID: 000000000006
Revises: 000000000005
Create Date: 2026-02-06 00:00:06.000000+00:00

- Add version column (code/model version) to execution_observations
- Backfill status column and observationstatus enum for deployed environments missing it (idempotent)
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000006"
down_revision: Union[str, None] = "000000000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add version column (all environments)
    op.add_column(
        "execution_observations",
        sa.Column("version", sa.String(50), nullable=True, comment="Code/model version"),
    )

    # 2. If the table exists but lacks the status column (environments that ran 000000000005 before status was merged), add the enum and column
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # Create observationstatus enum if it does not exist
        op.execute(
            sa.text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'observationstatus') THEN
                        CREATE TYPE observationstatus AS ENUM (
                            'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED'
                        );
                    END IF;
                END$$;
            """)
        )
        # Add status column if it does not exist
        op.execute(
            sa.text("""
                ALTER TABLE execution_observations
                ADD COLUMN IF NOT EXISTS status observationstatus
                NOT NULL DEFAULT 'RUNNING'::observationstatus
            """)
        )


def downgrade() -> None:
    op.drop_column("execution_observations", "version")
    # Do not automatically drop the status column to avoid breaking applications that depend on it.
    # To roll back manually:
    # ALTER TABLE execution_observations DROP COLUMN IF EXISTS status;
    # DROP TYPE IF EXISTS observationstatus;
