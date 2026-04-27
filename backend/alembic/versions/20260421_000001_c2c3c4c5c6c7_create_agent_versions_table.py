"""Create agent_versions table and add FK from agents.current_draft_version_id."""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "c2c3c4c5c6c7"
down_revision: Union[str, None] = "b1b2b3b4b5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("source_kind", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("definition_kind", sa.String(20), nullable=False),
        sa.Column("definition_payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("capability_manifest", JSONB(), nullable=False, server_default="{}"),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_id_version_number"),
    )

    op.create_foreign_key(
        "fk_agents_current_draft_version_id",
        "agents",
        "agent_versions",
        ["current_draft_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_current_draft_version_id", "agents", type_="foreignkey")
    op.drop_table("agent_versions")
