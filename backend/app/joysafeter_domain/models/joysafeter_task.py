from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.ids import AgentId, EntityIdType, SessionId, TaskId

from .base import JoySafeterBaseModel

# ---------------------------------------------------------------------------
# JoySafeter Task models
# ---------------------------------------------------------------------------


class JoySafeterTaskStatus(str, enum.Enum):
    PENDING = "pending"
    SCHEDULING = "scheduling"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in (
            JoySafeterTaskStatus.COMPLETED,
            JoySafeterTaskStatus.FAILED,
            JoySafeterTaskStatus.ABORTED,
            JoySafeterTaskStatus.TIMEOUT,
            JoySafeterTaskStatus.CANCELLED,
        )

    @classmethod
    def from_str_lossy(cls, s: str) -> "JoySafeterTaskStatus":
        try:
            return cls(s)
        except ValueError:
            return cls.FAILED


JOYSAFETER_TERMINAL_STATUSES = frozenset(s for s in JoySafeterTaskStatus if s.is_terminal())


class JoySafeterTask(JoySafeterBaseModel):
    __tablename__ = "joysafeter_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_joysafeter_tasks_idempotency_key"),
        Index("idx_ct_status", "status"),
        Index("idx_ct_agent", "agent_id"),
        Index("idx_ct_created", "created_at"),
        Index("idx_ct_project", "project_id"),
        Index("idx_ct_user_status", "user_id", "status"),
        Index("idx_ct_status_created", "status", "created_at"),
        Index("idx_ct_status_updated", "status", "updated_at"),
        Index("idx_ct_status_next_schedule", "status", "next_schedule_at"),
        Index("idx_ct_started", "started_at"),
        Index("idx_ct_completed", "completed_at"),
        Index("idx_ct_project_status_created", "project_id", "status", "created_at"),
        Index("idx_ct_sandbox_status", "sandbox_id", "status"),
        Index("idx_ct_sandbox_status_created", "sandbox_id", "status", "created_at"),
        Index(
            "idx_ct_running_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
        # Back-reference to the trigger that fired this task (NULL for
        # interactive tasks). Backs the trigger run-history query and the
        # concurrency-policy "is a prior fire still active?" check.
        Index("idx_ct_trigger", "trigger_id"),
    )

    id: Mapped[TaskId] = mapped_column(EntityIdType(TaskId), primary_key=True, default=TaskId.new)

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    # Tenant identity of the submitter, denormalized onto the task for
    # attribution/audit and per-user admission control. Deliberately NOT
    # FK-constrained so a task's audit record survives user/org deletion.
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[AgentId] = mapped_column(
        EntityIdType(AgentId),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    chat_session_id: Mapped[Optional[SessionId]] = mapped_column(
        EntityIdType(SessionId),
        ForeignKey("joysafeter_sessions.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sandbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=7200)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    schedule_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_schedule_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_schedule_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_schedule_error_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduling_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    owner_instance_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_epoch: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Set when this task was created by a trigger fire (cron/webhook/manual);
    # NULL for interactive tasks. References the unified joysafeter_triggers row.
    trigger_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_triggers.id", ondelete="SET NULL"),
        nullable=True,
    )
