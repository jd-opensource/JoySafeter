"""add isolated Rust xDS shadow ACK/NACK status

Revision ID: 20260803_000001
Revises: 20260731_000001
Create Date: 2026-08-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260803_000001"
down_revision: Union[str, None] = "20260731_000001"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_rust_xds_shadow_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_group_key", sa.String(length=96), nullable=False),
        sa.Column("node_group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("type_url", sa.String(length=255), nullable=False),
        sa.Column("xds_version", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("orchestrator_instance", sa.String(length=128), nullable=False),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("generation > 0", name="ck_rust_xds_shadow_generation_positive"),
        sa.CheckConstraint("status IN ('ack', 'nack')", name="ck_rust_xds_shadow_status"),
        sa.CheckConstraint(
            "nonce_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_rust_xds_shadow_nonce_sha256",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_rust_xds_shadow_generation",
        ),
        sa.UniqueConstraint(
            "source_group_key",
            "generation",
            "node_group_key",
            "node_id",
            "type_url",
            name="uq_rust_xds_shadow_observation",
        ),
    )
    op.create_index(
        "idx_rust_xds_shadow_generation",
        "joysafeter_rust_xds_shadow_status",
        ["source_group_key", "generation", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_rust_xds_shadow_generation",
        table_name="joysafeter_rust_xds_shadow_status",
    )
    op.drop_table("joysafeter_rust_xds_shadow_status")
