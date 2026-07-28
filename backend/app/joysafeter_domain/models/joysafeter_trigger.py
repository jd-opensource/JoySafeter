from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import JoySafeterBaseModel


class TriggerType(str, enum.Enum):
    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class TriggerSessionMode(str, enum.Enum):
    FRESH = "fresh"
    REUSE = "reuse"
    PINNED = "pinned"
    KEYED = "keyed"  # reuse bucketed by a payload-rendered session_key


class TriggerConcurrencyPolicy(str, enum.Enum):
    """What to do when a cron fire is due but a prior run is still active."""

    ALLOW = "allow"  # fire anyway (fresh session per fire makes this safe)
    FORBID = "forbid"  # skip this fire, log it, wait for the next slot
    REPLACE = "replace"  # cancel the still-active task(s), then fire


class JoySafeterTrigger(JoySafeterBaseModel):
    __tablename__ = "joysafeter_triggers"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_joysafeter_triggers_project_name"),
        Index("idx_joysafeter_triggers_project", "project_id"),
        Index("idx_joysafeter_triggers_type_enabled", "type", "enabled"),
        Index(
            "idx_joysafeter_triggers_cron_due",
            "next_run_at",
            postgresql_where=text("enabled IS TRUE AND type = 'cron'"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default=TriggerType.WEBHOOK.value)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("joysafeter_agents.id"), nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    environment_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    session_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fresh", server_default="fresh")
    session_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pinned_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"), nullable=True
    )
    reusable_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"), nullable=True
    )
    secret_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    secret_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    filter: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=7200, server_default="7200")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")

    cron_expr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    concurrency_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="allow", server_default="allow")
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_slot: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Slot retry / dead-letter state (cron control plane). ``pending_slot_at`` is
    # the slot instant currently being attempted so a backoff retry can reuse the
    # same logical slot (and its idempotency key); ``slot_attempts`` counts those
    # attempts. ``auto_disabled_at`` / ``disabled_reason`` record a dead-letter
    # (auto-disable) after the consecutive-failure threshold is crossed.
    pending_slot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    slot_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    auto_disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    locked_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_tasks.id", ondelete="SET NULL"), nullable=True
    )
    last_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"), nullable=True
    )
    last_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
