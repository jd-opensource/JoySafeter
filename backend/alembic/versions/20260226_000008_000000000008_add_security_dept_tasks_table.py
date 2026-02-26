"""add_security_dept_tasks_table

Revision ID: 000000000008
Revises: 000000000007
Create Date: 2026-02-26 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000008"
down_revision: Union[str, None] = "000000000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_dept_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario", sa.String(length=50), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("instruction_digest", sa.String(length=64), nullable=False),
        sa.Column("instruction_preview", sa.String(length=500), nullable=False),
        sa.Column(
            "selected_skills",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("result_structured", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("execution_stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_security_dept_tasks_status", "security_dept_tasks", ["status"], unique=False)
    op.create_index("ix_security_dept_tasks_user_id", "security_dept_tasks", ["user_id"], unique=False)
    op.create_index("ix_security_dept_tasks_workspace_id", "security_dept_tasks", ["workspace_id"], unique=False)
    op.create_index(
        "ix_security_dept_tasks_user_created",
        "security_dept_tasks",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_dept_tasks_user_status",
        "security_dept_tasks",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_security_dept_tasks_workspace_created",
        "security_dept_tasks",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_security_dept_tasks_workspace_created", table_name="security_dept_tasks")
    op.drop_index("ix_security_dept_tasks_user_status", table_name="security_dept_tasks")
    op.drop_index("ix_security_dept_tasks_user_created", table_name="security_dept_tasks")
    op.drop_index("ix_security_dept_tasks_workspace_id", table_name="security_dept_tasks")
    op.drop_index("ix_security_dept_tasks_user_id", table_name="security_dept_tasks")
    op.drop_index("ix_security_dept_tasks_status", table_name="security_dept_tasks")
    op.drop_table("security_dept_tasks")
