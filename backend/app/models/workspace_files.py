"""
文件存储相关模型
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, utc_now

if TYPE_CHECKING:
    from .auth import AuthUser
    from .workspace import Workspace


class WorkspaceFile(BaseModel):
    """工作空间文件（旧/简化表）"""

    __tablename__ = "workspace_file"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    uploader: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        Index("workspace_file_workspace_id_idx", "workspace_id"),
        Index("workspace_file_key_idx", "key"),
    )


class WorkspaceStoredFile(BaseModel):
    """统一文件存储表（多上下文）"""

    __tablename__ = "workspace_files"

    key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    context: Mapped[str] = mapped_column(String(50), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")

    __table_args__ = (
        Index("workspace_files_key_idx", "key"),
        Index("workspace_files_user_id_idx", "user_id"),
        Index("workspace_files_workspace_id_idx", "workspace_id"),
        Index("workspace_files_context_idx", "context"),
    )
