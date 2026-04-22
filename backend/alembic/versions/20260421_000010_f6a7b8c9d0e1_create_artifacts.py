"""create artifacts table"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"


def upgrade():
    op.create_table(
        "artifacts",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade():
    op.drop_table("artifacts")
