"""add Rust xDS shadow generation lifecycle

Revision ID: 20260803_000002
Revises: 20260803_000001
Create Date: 2026-08-03 01:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260803_000002"
down_revision: Union[str, None] = "20260803_000001"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_rust_xds_shadow_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_group_key", sa.String(length=96), nullable=False),
        sa.Column("node_group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("xds_version", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("rollback_version", sa.String(length=96), nullable=True),
        sa.Column("orchestrator_instance", sa.String(length=128), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("generation > 0", name="ck_rust_xds_shadow_lifecycle_generation"),
        sa.CheckConstraint(
            "state IN ('accepted', 'failed')",
            name="ck_rust_xds_shadow_lifecycle_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_rust_xds_shadow_lifecycle_generation",
        ),
        sa.UniqueConstraint(
            "source_group_key",
            "node_group_key",
            "generation",
            name="uq_rust_xds_shadow_generation_lifecycle",
        ),
    )
    op.create_index(
        "idx_rust_xds_shadow_last_good",
        "joysafeter_rust_xds_shadow_generations",
        ["source_group_key", "node_group_key", sa.text("generation DESC")],
        postgresql_where=sa.text("state = 'accepted'"),
    )
    op.create_index(
        "idx_rust_xds_shadow_failed",
        "joysafeter_rust_xds_shadow_generations",
        ["source_group_key", "generation"],
        postgresql_where=sa.text("state = 'failed'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_rust_xds_shadow_failed",
        table_name="joysafeter_rust_xds_shadow_generations",
    )
    op.drop_index(
        "idx_rust_xds_shadow_last_good",
        table_name="joysafeter_rust_xds_shadow_generations",
    )
    op.drop_table("joysafeter_rust_xds_shadow_generations")
