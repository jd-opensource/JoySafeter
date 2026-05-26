from __future__ import annotations

import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class CommentAuthorType(str, enum.Enum):
    MEMBER = "member"
    AGENT = "agent"


class CommentType(str, enum.Enum):
    COMMENT = "comment"
    STATUS_CHANGE = "status_change"
    PROGRESS_UPDATE = "progress_update"
    SYSTEM = "system"


class MissionComment(BaseModel):
    __tablename__ = "mission_comments"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_type: Mapped[CommentAuthorType] = mapped_column(
        Enum(CommentAuthorType, values_callable=lambda e: [m.value for m in e], name="commentauthortype"),
        nullable=False,
    )
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[CommentType] = mapped_column(
        Enum(CommentType, values_callable=lambda e: [m.value for m in e], name="commenttype"),
        nullable=False,
        default=CommentType.COMMENT,
    )
    parent_comment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mission_comments.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("mission_comments_mission_created_idx", "mission_id", "created_at"),
        Index("mission_comments_workspace_idx", "workspace_id"),
        Index("mission_comments_author_idx", "author_type", "author_id"),
        Index("mission_comments_parent_idx", "parent_comment_id"),
    )
