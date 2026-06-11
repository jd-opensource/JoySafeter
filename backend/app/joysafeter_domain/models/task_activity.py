from __future__ import annotations

import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ActivityAuthorType(str, enum.Enum):
    MEMBER = "member"
    AGENT = "agent"


class ActivityType(str, enum.Enum):
    COMMENT = "comment"
    STATUS_CHANGE = "status_change"
    PROGRESS_UPDATE = "progress_update"
    SYSTEM = "system"


class TaskActivity(BaseModel):
    __tablename__ = "task_activities"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"), nullable=False
    )
    author_type: Mapped[ActivityAuthorType] = mapped_column(
        Enum(ActivityAuthorType, values_callable=lambda e: [m.value for m in e], name="activityauthortype"),
        nullable=False,
    )
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, values_callable=lambda e: [m.value for m in e], name="activitytype"),
        nullable=False,
        default=ActivityType.COMMENT,
    )
    parent_activity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_activities.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("task_activities_task_created_idx", "task_id", "created_at"),
        Index("task_activities_project_idx", "project_id"),
        Index("task_activities_author_idx", "author_type", "author_id"),
        Index("task_activities_parent_idx", "parent_activity_id"),
    )
