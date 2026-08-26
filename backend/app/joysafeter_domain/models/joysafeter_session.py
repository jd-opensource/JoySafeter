from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import AgentId, EnvironmentId, EventId, ProjectId, SandboxId, SessionId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

from .base import JoySafeterModel


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


class JoySafeterSession(JoySafeterModel):
    __tablename__ = "joysafeter_sessions"
    __table_args__ = (
        Index("idx_csess_agent", "agent_id"),
        Index("idx_csess_created", "created_at"),
        Index("idx_csess_project", "project_id"),
        Index("idx_csess_updated", "updated_at"),
        Index("idx_csess_archived", "archived_at"),
    )

    id: Mapped[SessionId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(SessionId), primary_key=True
    )
    project_id: Mapped[Optional[ProjectId]] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[AgentId] = mapped_column(
        EntityIdType(AgentId),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=SessionStatus.IDLE.value)
    stop_reason: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    usage: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"input_tokens":0,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}',
    )
    active_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    agent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    environment_id: Mapped[Optional[EnvironmentId]] = mapped_column(
        EntityIdType(EnvironmentId),
        ForeignKey("joysafeter_environments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    last_harness_session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_work_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sandbox_id: Mapped[Optional[SandboxId]] = mapped_column(EntityIdType(SandboxId), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_config_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    runtime_config_generation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_config_generation_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    events: Mapped[list["JoySafeterSessionEvent"]] = relationship(
        back_populates="session",
        lazy="selectin",
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

    id: Mapped[EventId] = mapped_column(EntityIdType(EventId), primary_key=True)
    session_id: Mapped[SessionId] = mapped_column(
        EntityIdType(SessionId),
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
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["JoySafeterSession"] = relationship(back_populates="events")
