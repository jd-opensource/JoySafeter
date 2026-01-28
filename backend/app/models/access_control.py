"""
权限/邀请模型
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Optional, Tuple

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .workspace import Workspace


class PermissionType(str, PyEnum):
    admin = "admin"
    write = "write"
    read = "read"


class WorkspaceInvitationStatus(str, PyEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    cancelled = "cancelled"


class WorkspaceInvitation(BaseModel):
    """工作空间邀请"""

    __tablename__ = "workspace_invitation"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    inviter_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    status: Mapped[WorkspaceInvitationStatus] = mapped_column(
        Enum(WorkspaceInvitationStatus, name="workspaceinvitationstatus", create_type=False),
        nullable=False,
        default=WorkspaceInvitationStatus.pending,
    )
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    permissions: Mapped[PermissionType] = mapped_column(
        Enum(PermissionType, name="permissiontype", create_type=False),
        nullable=False,
        default=PermissionType.admin,
    )
    org_invitation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    inviter: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    # 索引优化：加速邀请查询
    __table_args__: Tuple = (
        # 用于查询用户待处理邀请（按 email + status 查询）
        Index("workspace_invitation_email_status_idx", "email", "status"),
        # 用于查询过期邀请
        Index("workspace_invitation_expires_at_idx", "expires_at"),
        # 用于查询工作空间的所有邀请
        Index("workspace_invitation_workspace_id_idx", "workspace_id"),
    )


class Permission(BaseModel):
    """权限表（用户对实体的权限）"""

    __tablename__ = "permissions"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    permission_type: Mapped[PermissionType] = mapped_column(
        Enum(PermissionType, name="permissiontype", create_type=False),
        nullable=False,
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        Index("permissions_user_id_idx", "user_id"),
        Index("permissions_entity_idx", "entity_type", "entity_id"),
        Index("permissions_user_entity_type_idx", "user_id", "entity_type"),
        Index("permissions_user_entity_permission_idx", "user_id", "entity_type", "permission_type"),
        Index("permissions_user_entity_idx", "user_id", "entity_type", "entity_id"),
        UniqueConstraint("user_id", "entity_type", "entity_id", name="permissions_unique_constraint"),
    )
