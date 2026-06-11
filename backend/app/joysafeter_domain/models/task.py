from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, JoySafeterBaseModel

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_run import AgentRun
    from .thread import Thread


class TaskStatus(str, enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Task(BaseModel):
    __tablename__ = "tasks"

    project_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, values_callable=lambda e: [m.value for m in e], name="taskstatus"),
        nullable=False,
        default=TaskStatus.BACKLOG,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, values_callable=lambda e: [m.value for m in e], name="taskpriority"),
        nullable=False,
        default=TaskPriority.NONE,
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=False,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id"),
        nullable=False,
    )
    creator_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    latest_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", use_alter=True),
        nullable=True,
    )

    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    latest_run: Mapped[Optional["AgentRun"]] = relationship("AgentRun", foreign_keys=[latest_run_id])
    thread: Mapped["Thread"] = relationship("Thread", foreign_keys=[thread_id])

    __table_args__ = (
        Index("tasks_project_status_idx", "project_id", "status"),
        Index("tasks_agent_idx", "agent_id"),
        Index("tasks_creator_idx", "creator_id", "created_at"),
    )


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
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True, index=True,
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
    sandbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=7200)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
