from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_utils import uuid7

from app.core.database import Base
from app.utils.datetime import utc_now

from .base import BaseModel, ConductorBaseModel, TimestampMixin

if TYPE_CHECKING:
    from .agent import Agent


class Thread(BaseModel):
    """A conversation thread between a user and an agent.

    Thread is the session root: it owns the container, the CLI session id,
    and the session_id under which all Traces for its AgentRuns are grouped.
    """

    __tablename__ = "threads"

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
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
# Conductor Session models
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


class ConductorSession(ConductorBaseModel):
    __tablename__ = "conductor_sessions"
    __table_args__ = (
        Index("idx_csess_agent", "agent_id"),
        Index("idx_csess_created", "created_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_agents.id"),
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

    events: Mapped[list["ConductorSessionEvent"]] = relationship(
        back_populates="session", lazy="selectin",
        cascade="all, delete-orphan",
    )


class ConductorSessionEvent(Base):
    __tablename__ = "conductor_session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        Index("idx_cse_session_seq", "session_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=lambda ctx=None: uuid7()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_sessions.id"),
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

    session: Mapped["ConductorSession"] = relationship(back_populates="events")
