"""create agent_releases table and add FK on agents.active_release_id"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "e4e5e6e7e8e9"
down_revision = "d3d4d5d6d7d8"

def upgrade():
    op.create_table(
        "agent_releases",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_version_id", UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("release_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column("runtime_kind", sa.String(20), nullable=False),
        sa.Column("builder_kind", sa.String(20), nullable=True),
        sa.Column("executable_ref", JSONB, nullable=True),
        sa.Column("runtime_binding", JSONB, nullable=False, server_default="{}"),
        sa.Column("published_by", sa.String(255), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_version_id", "release_number", name="uq_agent_releases_version_number"),
    )
    # Add the circular FK from agents.active_release_id -> agent_releases.id
    op.create_foreign_key(
        "fk_agents_active_release",
        "agents", "agent_releases",
        ["active_release_id"], ["id"],
    )

def downgrade():
    op.drop_constraint("fk_agents_active_release", "agents", type_="foreignkey")
    op.drop_table("agent_releases")
