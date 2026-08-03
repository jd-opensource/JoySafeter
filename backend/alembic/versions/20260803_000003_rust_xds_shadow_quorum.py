"""add Rust xDS shadow connection leases and quorum evidence

Revision ID: 20260803_000003
Revises: 20260803_000002
Create Date: 2026-08-03 02:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260803_000003"
down_revision: Union[str, None] = "20260803_000002"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_rust_xds_shadow_generations",
        sa.Column("required_type_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "joysafeter_rust_xds_shadow_generations",
        sa.Column("connected_nodes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "joysafeter_rust_xds_shadow_generations",
        sa.Column("required_acks", sa.Integer(), nullable=True),
    )
    op.add_column(
        "joysafeter_rust_xds_shadow_generations",
        sa.Column("acked_acks", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_rust_xds_shadow_lifecycle_quorum",
        "joysafeter_rust_xds_shadow_generations",
        """
        (required_type_urls IS NULL AND connected_nodes IS NULL
         AND required_acks IS NULL AND acked_acks IS NULL)
        OR
        (jsonb_typeof(required_type_urls) = 'array'
         AND jsonb_array_length(required_type_urls) > 0
         AND connected_nodes > 0
         AND required_acks = connected_nodes * jsonb_array_length(required_type_urls)
         AND acked_acks = required_acks)
        """,
    )

    op.create_table(
        "joysafeter_rust_xds_shadow_node_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_group_key", sa.String(length=96), nullable=False),
        sa.Column("node_group_key", sa.String(length=96), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("orchestrator_instance", sa.String(length=128), nullable=False),
        sa.Column("sync_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "lease_expires_at > last_seen_at",
            name="ck_rust_xds_shadow_connection_lease_future",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "node_group_key",
            "node_id",
            name="uq_rust_xds_shadow_node_connection",
        ),
    )
    op.create_index(
        "idx_rust_xds_shadow_node_connection_active",
        "joysafeter_rust_xds_shadow_node_connections",
        ["source_group_key", "node_group_key", "lease_expires_at"],
        postgresql_where=sa.text("disconnected_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_rust_xds_shadow_node_connection_active",
        table_name="joysafeter_rust_xds_shadow_node_connections",
    )
    op.drop_table("joysafeter_rust_xds_shadow_node_connections")
    op.drop_constraint(
        "ck_rust_xds_shadow_lifecycle_quorum",
        "joysafeter_rust_xds_shadow_generations",
        type_="check",
    )
    op.drop_column("joysafeter_rust_xds_shadow_generations", "acked_acks")
    op.drop_column("joysafeter_rust_xds_shadow_generations", "required_acks")
    op.drop_column("joysafeter_rust_xds_shadow_generations", "connected_nodes")
    op.drop_column("joysafeter_rust_xds_shadow_generations", "required_type_urls")
