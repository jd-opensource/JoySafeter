from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import JoySafeterBaseModel


class JoySafeterEgressGroupGeneration(JoySafeterBaseModel):
    __tablename__ = "joysafeter_egress_group_generations"
    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_egress_group_generation_positive"),
        CheckConstraint("policy_schema_version > 0", name="ck_egress_policy_schema_positive"),
        CheckConstraint("group_key ~ '^v1:[A-Za-z0-9_-]{43}$'", name="ck_egress_group_key_format"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_egress_content_sha256_format"),
        CheckConstraint("jsonb_typeof(node_selector) = 'object'", name="ck_egress_node_selector_object"),
        CheckConstraint(
            "node_selector ?& ARRAY['deployment_id', 'environment', 'region', 'provider', "
            "'shard_id', 'envoy_version', 'config_schema_version']",
            name="ck_egress_node_selector_required_keys",
        ),
        CheckConstraint(
            "node_selector->>'provider' <> 'docker' OR NULLIF(BTRIM(node_selector->>'host_id'), '') IS NOT NULL",
            name="ck_egress_docker_selector_host",
        ),
        CheckConstraint("jsonb_typeof(desired_policies) = 'array'", name="ck_egress_desired_policies_array"),
        CheckConstraint("state IN ('desired', 'superseded', 'retired')", name="ck_egress_group_generation_state"),
        UniqueConstraint("group_key", "generation", name="uq_egress_group_generation"),
        Index(
            "idx_egress_group_generation_current",
            "group_key",
            text("generation DESC"),
            postgresql_where=text("state = 'desired'"),
        ),
    )

    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_selector: Mapped[dict] = mapped_column(JSONB, nullable=False)
    policy_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    desired_policies: Mapped[list] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="desired", server_default="desired")
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterEgressOutboxEvent(JoySafeterBaseModel):
    __tablename__ = "joysafeter_egress_outbox_events"
    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_egress_outbox_generation_positive"),
        ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_outbox_group_generation",
        ),
        UniqueConstraint("group_key", "generation", "event_type", name="uq_egress_outbox_event"),
        Index("idx_egress_outbox_generation", "group_key", "generation", "created_at"),
    )

    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)


class JoySafeterEgressApplyStatus(JoySafeterBaseModel):
    __tablename__ = "joysafeter_egress_apply_status"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'published', 'applied', 'failed', 'superseded')",
            name="ck_egress_apply_state",
        ),
        CheckConstraint(
            "jsonb_typeof(required_type_urls) = 'array' AND jsonb_array_length(required_type_urls) > 0",
            name="ck_egress_apply_required_types",
        ),
        CheckConstraint(
            "connected_nodes >= 0 AND required_acks >= 0 AND acked_acks >= 0 AND acked_acks <= required_acks",
            name="ck_egress_apply_ack_counts",
        ),
        ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_apply_group_generation",
        ),
        UniqueConstraint("group_key", "generation", name="uq_egress_apply_group_generation"),
        Index("idx_egress_apply_state", "state", "updated_at"),
    )

    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    xds_version: Mapped[str] = mapped_column(String(96), nullable=False)
    required_type_urls: Mapped[list] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    connected_nodes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    required_acks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    acked_acks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reason_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    first_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterEgressNodeConnection(JoySafeterBaseModel):
    __tablename__ = "joysafeter_egress_node_connections"
    __table_args__ = (
        CheckConstraint(
            "group_key ~ '^v1:[A-Za-z0-9_-]{43}$'",
            name="ck_egress_connection_group_key_format",
        ),
        CheckConstraint("lease_expires_at > last_seen_at", name="ck_egress_connection_lease_future"),
        UniqueConstraint("group_key", "node_id", name="uq_egress_node_connection"),
        Index(
            "idx_egress_node_connection_active",
            "group_key",
            "lease_expires_at",
            postgresql_where=text("disconnected_at IS NULL"),
        ),
    )

    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    controller_instance: Mapped[str] = mapped_column(String(128), nullable=False)
    envoy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), server_default=func.now()
    )
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterEgressNodeApplyStatus(JoySafeterBaseModel):
    __tablename__ = "joysafeter_egress_node_apply_status"
    __table_args__ = (
        CheckConstraint("status IN ('ack', 'nack')", name="ck_egress_node_apply_status"),
        CheckConstraint(
            "nonce_sha256 IS NULL OR nonce_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_egress_nonce_sha256_format",
        ),
        ForeignKeyConstraint(
            ["group_key", "generation"],
            [
                "joysafeter_egress_group_generations.group_key",
                "joysafeter_egress_group_generations.generation",
            ],
            ondelete="CASCADE",
            name="fk_egress_node_apply_group_generation",
        ),
        UniqueConstraint("group_key", "generation", "node_id", "type_url", name="uq_egress_node_apply_resource"),
        Index("idx_egress_node_apply_generation", "group_key", "generation", "status"),
    )

    group_key: Mapped[str] = mapped_column(String(96), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    type_url: Mapped[str] = mapped_column(String(255), nullable=False)
    xds_version: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    nonce_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    controller_instance: Mapped[str] = mapped_column(String(128), nullable=False)
    error_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), server_default=func.now()
    )
