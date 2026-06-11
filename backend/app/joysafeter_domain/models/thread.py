from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_utils import uuid7

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now

from .base import BaseModel, JoySafeterBaseModel, TimestampMixin

if TYPE_CHECKING:
    from .agent import Agent


class Thread(BaseModel):
    """A conversation thread between a user and an agent.

    Thread is the session root: it owns the container, the CLI session id,
    and the session_id under which all Traces for its AgentRuns are grouped.
    """

    __tablename__ = "threads"

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id"), nullable=False)

    # Engine identity -- populated lazily by the container pool
    container_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cli_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    agent: Mapped[Agent] = relationship("Agent")

    __table_args__ = (
        Index(
            "idx_threads_lru",
            "last_active_at",
            postgresql_where="status = 'active'",
            postgresql_ops={"last_active_at": "DESC"},
        ),
    )


# ---------------------------------------------------------------------------
# JoySafeter Session models
# ---------------------------------------------------------------------------


class SessionStatus(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    RESCHEDULING = "rescheduling"
    TERMINATED = "terminated"

    @classmethod
    def from_str_lossy(cls, s: str) -> "SessionStatus":
        try:
            return cls(s)
        except ValueError:
            return cls.TERMINATED


class JoySafeterSession(JoySafeterBaseModel):
    __tablename__ = "joysafeter_sessions"
    __table_args__ = (
        Index("idx_csess_agent", "agent_id"),
        Index("idx_csess_created", "created_at"),
        Index("idx_csess_project", "project_id"),
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="idle")
    stop_reason: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    usage: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"input_tokens":0,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}',
    )
    active_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    vault_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    agent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    environment_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_harness_session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_work_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sandbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    events: Mapped[list["JoySafeterSessionEvent"]] = relationship(
        back_populates="session", lazy="selectin",
        cascade="all, delete-orphan",
    )


class JoySafeterSessionEvent(Base):
    __tablename__ = "joysafeter_session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        Index("idx_cse_session_seq", "session_id", "seq"),
        Index("idx_cse_session_event_seq", "session_id", "event_type", "seq"),
        Index("idx_cse_created_at", "created_at"),
        Index("idx_cse_event_created", "event_type", "created_at"),
        Index("idx_cse_session_processed_event", "session_id", "processed_at", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=lambda ctx=None: uuid7()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_sessions.id"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped["JoySafeterSession"] = relationship(back_populates="events")
