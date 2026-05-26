from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .base import BaseModel, TimestampMixin


class MissionExecutionStatus(str, enum.Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    INTERRUPT_WAIT = "interrupt_wait"  # Reserved: legacy AgentRun status, not used in execution flow
    APPROVAL_WAIT = "approval_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_EXECUTION_STATUSES: frozenset[MissionExecutionStatus] = frozenset(
    {
        MissionExecutionStatus.COMPLETED,
        MissionExecutionStatus.FAILED,
        MissionExecutionStatus.CANCELLED,
    }
)


class ExecutionSource(str, enum.Enum):
    MISSION = "mission"
    CHAT = "chat"
    GRAPH = "graph"
    COORDINATOR = "coordinator"
    API = "api"


class Execution(BaseModel):
    __tablename__ = "executions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    source: Mapped[ExecutionSource] = mapped_column(
        Enum(ExecutionSource, values_callable=lambda e: [m.value for m in e], name="executionsource"),
        nullable=False,
    )
    status: Mapped[MissionExecutionStatus] = mapped_column(
        Enum(MissionExecutionStatus, values_callable=lambda e: [m.value for m in e], name="missionexecutionstatus"),
        nullable=False,
        default=MissionExecutionStatus.QUEUED,
    )
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    runtime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    runtime_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    prior_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    work_dir: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    trigger_comment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mission_comments.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("executions_workspace_status_idx", "workspace_id", "status"),
        Index("executions_mission_idx", "mission_id"),
        Index("executions_agent_profile_idx", "agent_profile_id"),
        Index("executions_parent_idx", "parent_execution_id"),
        Index("executions_user_created_idx", "user_id", "created_at"),
        Index("executions_trigger_comment_idx", "trigger_comment_id"),
    )


class ExecutionEvent(BaseModel):
    __tablename__ = "execution_events"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("execution_id", "seq", name="uq_execution_events_exec_seq"),
        Index("execution_events_exec_created_idx", "execution_id", "created_at"),
    )


class ExecutionSnapshot(Base, TimestampMixin):
    __tablename__ = "execution_snapshots"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
