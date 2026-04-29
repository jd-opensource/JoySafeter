"""extend agent_release_status enum with active and superseded

Revision ID: ee5ff6aa7bb8
Revises: dd4ee5ff6aa7
Create Date: 2026-04-29 00:00:00.000000+00:00

Changes:
- agent_release_status enum: add 'active' and 'superseded' values
- Backfill: each agent's active_release_id row -> 'active'
- Backfill: sibling 'ready' rows (same agent, has active sibling) -> 'superseded'
"""

from typing import Sequence, Union

from alembic import op

revision: str = "ee5ff6aa7bb8"
down_revision: Union[str, None] = "dd4ee5ff6aa7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE agent_release_status ADD VALUE IF NOT EXISTS 'active'")
        op.execute("ALTER TYPE agent_release_status ADD VALUE IF NOT EXISTS 'superseded'")

    op.execute(
        """
        UPDATE agent_releases r
           SET status = 'active'
          FROM agents a
         WHERE a.active_release_id = r.id
           AND r.status = 'ready'
        """
    )

    op.execute(
        """
        UPDATE agent_releases r
           SET status = 'superseded'
          FROM agent_versions v
         WHERE r.agent_version_id = v.id
           AND r.status = 'ready'
           AND EXISTS (
                SELECT 1 FROM agent_releases r2
                  JOIN agent_versions v2 ON r2.agent_version_id = v2.id
                 WHERE v2.agent_id = v.agent_id
                   AND r2.status = 'active'
           )
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE agent_releases SET status = 'ready' "
        "WHERE status IN ('active', 'superseded')"
    )
