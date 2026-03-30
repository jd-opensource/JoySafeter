"""add model_usage_log table

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-03-30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "q2r3s4t5u6v7"
down_revision: Union[str, None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_usage_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False, server_default="chat"),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_time_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="chat"),
    )
    op.create_index("model_usage_log_created_at_idx", "model_usage_log", ["created_at"])
    op.create_index("model_usage_log_provider_model_idx", "model_usage_log", ["provider_name", "model_name"])
    op.create_index(
        "model_usage_log_created_provider_model_idx",
        "model_usage_log",
        ["created_at", "provider_name", "model_name"],
    )


def downgrade() -> None:
    op.drop_index("model_usage_log_created_provider_model_idx", table_name="model_usage_log")
    op.drop_index("model_usage_log_provider_model_idx", table_name="model_usage_log")
    op.drop_index("model_usage_log_created_at_idx", table_name="model_usage_log")
    op.drop_table("model_usage_log")
