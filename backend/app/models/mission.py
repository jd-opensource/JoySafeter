from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MissionStatus(str, enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class AssigneeType(str, enum.Enum):
    AGENT = "agent"
    MEMBER = "member"


class MissionPriority(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Mission(BaseModel):
    __tablename__ = "missions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus, values_callable=lambda e: [m.value for m in e], name="missionstatus"),
        nullable=False,
        default=MissionStatus.BACKLOG,
    )
    priority: Mapped[MissionPriority] = mapped_column(
        Enum(MissionPriority, values_callable=lambda e: [m.value for m in e], name="missionpriority"),
        nullable=False,
        default=MissionPriority.NONE,
    )

    assignee_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    creator_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("missions_workspace_status_idx", "workspace_id", "status"),
        Index("missions_assignee_idx", "assignee_type", "assignee_id"),
        Index("missions_creator_idx", "creator_id", "created_at"),
    )
