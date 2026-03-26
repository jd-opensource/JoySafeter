"""
Agent run persistence models.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.utils.datetime import utc_now

from .base import BaseModel, TimestampMixin


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    INTERRUPT_WAIT = "interrupt_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRun(BaseModel):
    """Durable long-running task record."""

    __tablename__ = "agent_runs"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    graph_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="SET NULL"),
        nullable=True,
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    run_type: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, values_callable=lambda e: [m.value for m in e], name="agentrunstatus"),
        nullable=False,
        default=AgentRunStatus.QUEUED,
    )

    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_owner_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    trace_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        Index("agent_runs_user_created_idx", "user_id", "created_at"),
        Index("agent_runs_thread_created_idx", "thread_id", "created_at"),
        Index("agent_runs_graph_created_idx", "graph_id", "created_at"),
        Index("agent_runs_status_updated_idx", "status", "updated_at"),
        Index("agent_runs_agent_updated_idx", "agent_name", "updated_at"),
        Index("agent_runs_owner_status_idx", "runtime_owner_id", "status"),
    )


class AgentRunEvent(BaseModel):
    """Append-only ordered event stream for a run."""

    __tablename__ = "agent_run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_run_events_run_seq"),
        Index("agent_run_events_run_created_idx", "run_id", "created_at"),
    )


class AgentRunSnapshot(Base, TimestampMixin):
    """Latest UI projection for a run."""

    __tablename__ = "agent_run_snapshots"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
