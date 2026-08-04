"""add durable Envoy egress control-plane state

Revision ID: 20260731_000001
Revises: 20260729_000001
Create Date: 2026-07-31 00:00:00.000000

The immutable group-generation row is the source of truth consumed by every
controller replica. The transactional event log accelerates delivery through
LISTEN/NOTIFY; periodic full reconciliation remains authoritative. Apply status is separated into an
aggregate row and per-node/resource ACK rows so a controller restart never
turns an unacknowledged policy into an accepted one.

All JSON documents are ref-only desired policy. Secret values are forbidden by
the application schema and must never be written to these tables.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260731_000001"
down_revision: Union[str, None] = "20260729_000001"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "joysafeter_egress_group_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("node_selector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_schema_version", sa.Integer(), nullable=False),
        sa.Column("desired_policies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="desired", nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("generation > 0", name="ck_egress_group_generation_positive"),
        sa.CheckConstraint("policy_schema_version > 0", name="ck_egress_policy_schema_positive"),
        sa.CheckConstraint(
            "group_key ~ '^v1:[A-Za-z0-9_-]{43}$'",
            name="ck_egress_group_key_format",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_egress_content_sha256_format",
        ),
        sa.CheckConstraint("jsonb_typeof(node_selector) = 'object'", name="ck_egress_node_selector_object"),
        sa.CheckConstraint(
            "node_selector ?& ARRAY['deployment_id', 'environment', 'region', 'provider', "
            "'shard_id', 'envoy_version', 'config_schema_version']",
            name="ck_egress_node_selector_required_keys",
        ),
        sa.CheckConstraint(
            "node_selector->>'provider' <> 'docker' OR NULLIF(BTRIM(node_selector->>'host_id'), '') IS NOT NULL",
            name="ck_egress_docker_selector_host",
        ),
        sa.CheckConstraint("jsonb_typeof(desired_policies) = 'array'", name="ck_egress_desired_policies_array"),
        sa.CheckConstraint(
            "state IN ('desired', 'superseded', 'retired')",
            name="ck_egress_group_generation_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_key", "generation", name="uq_egress_group_generation"),
    )
    op.create_index(
        "idx_egress_group_generation_current",
        "joysafeter_egress_group_generations",
        ["group_key", sa.text("generation DESC")],
        postgresql_where=sa.text("state = 'desired'"),
    )
    op.execute(
        """
        CREATE FUNCTION joysafeter_enforce_egress_generation_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.group_key IS DISTINCT FROM OLD.group_key
               OR NEW.generation IS DISTINCT FROM OLD.generation
               OR NEW.node_selector IS DISTINCT FROM OLD.node_selector
               OR NEW.policy_schema_version IS DISTINCT FROM OLD.policy_schema_version
               OR NEW.desired_policies IS DISTINCT FROM OLD.desired_policies
               OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'egress generation content is immutable: %/%', OLD.group_key, OLD.generation
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_joysafeter_egress_generation_immutable
        BEFORE UPDATE ON joysafeter_egress_group_generations
        FOR EACH ROW
        EXECUTE FUNCTION joysafeter_enforce_egress_generation_immutable()
        """
    )

    op.create_table(
        "joysafeter_egress_outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("generation > 0", name="ck_egress_outbox_generation_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_outbox_group_generation",
        ),
        sa.UniqueConstraint("group_key", "generation", "event_type", name="uq_egress_outbox_event"),
    )
    op.create_index(
        "idx_egress_outbox_generation",
        "joysafeter_egress_outbox_events",
        ["group_key", "generation", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION joysafeter_notify_egress_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_notify(
                'joysafeter_egress_generation',
                NEW.group_key || ':' || NEW.generation::text
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_joysafeter_egress_generation_notify
        AFTER INSERT ON joysafeter_egress_outbox_events
        FOR EACH ROW
        EXECUTE FUNCTION joysafeter_notify_egress_generation()
        """
    )

    op.create_table(
        "joysafeter_egress_node_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("controller_instance", sa.String(length=128), nullable=False),
        sa.Column("envoy_version", sa.String(length=64), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "group_key ~ '^v1:[A-Za-z0-9_-]{43}$'",
            name="ck_egress_connection_group_key_format",
        ),
        sa.CheckConstraint(
            "lease_expires_at > last_seen_at",
            name="ck_egress_connection_lease_future",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_key", "node_id", name="uq_egress_node_connection"),
    )
    op.create_index(
        "idx_egress_node_connection_active",
        "joysafeter_egress_node_connections",
        ["group_key", "lease_expires_at"],
        postgresql_where=sa.text("disconnected_at IS NULL"),
    )

    op.create_table(
        "joysafeter_egress_apply_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("xds_version", sa.String(length=96), nullable=False),
        sa.Column("required_type_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("connected_nodes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("required_acks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("acked_acks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'published', 'applied', 'failed', 'superseded')",
            name="ck_egress_apply_state",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_type_urls) = 'array' AND jsonb_array_length(required_type_urls) > 0",
            name="ck_egress_apply_required_types",
        ),
        sa.CheckConstraint(
            "connected_nodes >= 0 AND required_acks >= 0 AND acked_acks >= 0 AND acked_acks <= required_acks",
            name="ck_egress_apply_ack_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_apply_group_generation",
        ),
        sa.UniqueConstraint("group_key", "generation", name="uq_egress_apply_group_generation"),
    )
    op.create_index("idx_egress_apply_state", "joysafeter_egress_apply_status", ["state", "updated_at"])
    op.execute(
        """
        CREATE FUNCTION joysafeter_notify_egress_apply_status()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.state IS DISTINCT FROM OLD.state THEN
                PERFORM pg_notify(
                    'joysafeter_egress_apply_status',
                    NEW.group_key || ':' || NEW.generation::text
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_joysafeter_egress_apply_status_notify
        AFTER INSERT OR UPDATE ON joysafeter_egress_apply_status
        FOR EACH ROW
        EXECUTE FUNCTION joysafeter_notify_egress_apply_status()
        """
    )

    op.create_table(
        "joysafeter_egress_node_apply_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("type_url", sa.String(length=255), nullable=False),
        sa.Column("xds_version", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=True),
        sa.Column("controller_instance", sa.String(length=128), nullable=False),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ack', 'nack')", name="ck_egress_node_apply_status"),
        sa.CheckConstraint(
            "nonce_sha256 IS NULL OR nonce_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_egress_nonce_sha256_format",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_node_apply_group_generation",
        ),
        sa.UniqueConstraint(
            "group_key",
            "generation",
            "node_id",
            "type_url",
            name="uq_egress_node_apply_resource",
        ),
    )
    op.create_index(
        "idx_egress_node_apply_generation",
        "joysafeter_egress_node_apply_status",
        ["group_key", "generation", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_egress_node_apply_generation", table_name="joysafeter_egress_node_apply_status")
    op.drop_table("joysafeter_egress_node_apply_status")
    op.execute("DROP TRIGGER IF EXISTS trg_joysafeter_egress_apply_status_notify ON joysafeter_egress_apply_status")
    op.execute("DROP FUNCTION IF EXISTS joysafeter_notify_egress_apply_status()")
    op.drop_index("idx_egress_apply_state", table_name="joysafeter_egress_apply_status")
    op.drop_table("joysafeter_egress_apply_status")
    op.drop_index("idx_egress_node_connection_active", table_name="joysafeter_egress_node_connections")
    op.drop_table("joysafeter_egress_node_connections")
    op.execute("DROP TRIGGER IF EXISTS trg_joysafeter_egress_generation_notify ON joysafeter_egress_outbox_events")
    op.execute("DROP FUNCTION IF EXISTS joysafeter_notify_egress_generation()")
    op.drop_index("idx_egress_outbox_generation", table_name="joysafeter_egress_outbox_events")
    op.drop_table("joysafeter_egress_outbox_events")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_joysafeter_egress_generation_immutable ON joysafeter_egress_group_generations"
    )
    op.execute("DROP FUNCTION IF EXISTS joysafeter_enforce_egress_generation_immutable()")
    op.drop_index("idx_egress_group_generation_current", table_name="joysafeter_egress_group_generations")
    op.drop_table("joysafeter_egress_group_generations")
