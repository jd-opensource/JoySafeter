from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

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
        Index("idx_ct_status_created", "status", "created_at"),
        Index("idx_ct_status_updated", "status", "updated_at"),
        Index("idx_ct_project_status_created", "project_id", "status", "created_at"),
        Index("idx_ct_sandbox_status", "sandbox_id", "status"),
        Index("idx_ct_sandbox_status_created", "sandbox_id", "status", "created_at"),
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
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
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
