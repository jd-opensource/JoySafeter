"""add_copilot_chats_agent_graph_id_idx

Revision ID: 000000000001
Revises: 000000000000
Create Date: 2026-01-08 00:00:01.000000+00:00

Add missing index for copilot_chats.agent_graph_id to align ORM model with DB schema.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000001"
down_revision: Union[str, None] = "000000000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "copilot_chats_agent_graph_id_idx",
        "copilot_chats",
        ["agent_graph_id"],
    )


def downgrade() -> None:
    op.drop_index("copilot_chats_agent_graph_id_idx", table_name="copilot_chats")
