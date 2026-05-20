import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.core.database import Base
from app.models.base import TimestampMixin


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    SCHEDULING = "scheduling"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.ABORTED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        )

    @classmethod
    def from_str_lossy(cls, s: str) -> "TaskStatus":
        try:
            return cls(s)
        except ValueError:
            return cls.FAILED


TERMINAL_STATUSES = frozenset(s for s in TaskStatus if s.is_terminal())


class ConductorTask(BaseModel):
    __tablename__ = "conductor_tasks"
    __table_args__ = (
        Index("idx_ct_status", "status"),
        Index("idx_ct_agent", "agent_id"),
        Index("idx_ct_created", "created_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_agents.id"),
        nullable=False,
    )
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_sessions.id"),
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
