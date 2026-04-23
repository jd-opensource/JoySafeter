from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.utils.datetime import utc_now

if TYPE_CHECKING:
    from .agent import AgentRelease
    from .execution import Execution


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_releases.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    thread_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False)
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("queued", "running", "succeeded", "failed", "cancelled", name="agent_run_status"),
        nullable=False,
        default="queued",
    )
    current_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    release: Mapped["AgentRelease"] = relationship("AgentRelease")
    current_execution: Mapped[Optional["Execution"]] = relationship("Execution", foreign_keys=[current_execution_id])
    executions: Mapped[List["Execution"]] = relationship("Execution", back_populates="run", foreign_keys="Execution.run_id")
