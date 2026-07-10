from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import JoySafeterBaseModel

# ---------------------------------------------------------------------------
# JoySafeter Schedule model
#
# A schedule is a cron-driven trigger that, at each fire time, submits a task
# through the SAME path the HTTP API uses (TaskSubmissionService). All the
# reliability of the Rust task engine (lease, owner_epoch fencing, watchdog
# reclaim, idempotency, delayed retry, event-stream results) is therefore
# inherited for free — the scheduler itself only decides *when* to submit.
# ---------------------------------------------------------------------------


class ScheduleConcurrencyPolicy(str, enum.Enum):
    """What to do when a fire is due but the schedule's previous run is still active."""

    ALLOW = "allow"  # fire anyway (fresh session per fire makes this safe)
    FORBID = "forbid"  # skip this fire, log it, wait for the next slot
    REPLACE = "replace"  # cancel the still-active task, then fire


class JoySafeterSchedule(JoySafeterBaseModel):
    __tablename__ = "joysafeter_schedules"
    __table_args__ = (
        # Schedule names are unique within a project (NULL project => global scope).
        UniqueConstraint("project_id", "name", name="uq_joysafeter_schedules_project_name"),
        # The poller's only hot query: due, enabled schedules ordered by next_run_at.
        # Partial index keeps the scan cheap and excludes disabled rows.
        Index(
            "idx_joysafeter_schedules_due",
            "next_run_at",
            postgresql_where=text("enabled IS TRUE"),
        ),
        Index("idx_joysafeter_schedules_project", "project_id"),
    )

    # --- Identity / metadata ---
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- What to run (mirrors a task submission) ---
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    environment_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=7200)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # --- When to run ---
    cron_expr: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    concurrency_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ScheduleConcurrencyPolicy.ALLOW.value,
        server_default=ScheduleConcurrencyPolicy.ALLOW.value,
    )
    # The next cron instant this schedule is due (UTC). The poller claims rows
    # whose next_run_at <= now(). NULL only transiently before first compute.
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # The cron slot most recently fired — used as the aligned idempotency key and
    # to implement "catch up once and advance" on restart after downtime.
    last_fired_slot: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Submitter identity, captured at creation so each fire attributes and
    # passes tenant quota exactly like an interactive submission. ---
    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # --- Poller claim lock (SKIP LOCKED). A worker that claims a due schedule
    # stamps these; a stale lock (worker crash) is reclaimable after a grace. ---
    locked_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
