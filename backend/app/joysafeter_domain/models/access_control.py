"""
Permission and invitation models
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Optional, Tuple

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class PermissionType(str, PyEnum):
    admin = "admin"
    write = "write"
    read = "read"


class ProjectInvitationStatus(str, PyEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    cancelled = "cancelled"


class ProjectInvitation(BaseModel):
    """Project invitation."""

    __tablename__ = "project_invitation"

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    inviter_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    status: Mapped[ProjectInvitationStatus] = mapped_column(
        Enum(ProjectInvitationStatus, name="projectinvitationstatus", create_type=False),
        nullable=False,
        default=ProjectInvitationStatus.pending,
    )
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    permissions: Mapped[PermissionType] = mapped_column(
        Enum(PermissionType, name="permissiontype", create_type=False),
        nullable=False,
        default=PermissionType.admin,
    )
    org_invitation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    inviter: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    # index optimization: speed up invitation queries
    __table_args__: Tuple = (
        # look up pending invitations by email + status
        Index("project_invitation_email_status_idx", "email", "status"),
        # look up expired invitations
        Index("project_invitation_expires_at_idx", "expires_at"),
        # look up all invitations for a project
        Index("project_invitation_project_id_idx", "project_id"),
    )


class Permission(BaseModel):
    """Permission table (user permissions on entities)."""

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
