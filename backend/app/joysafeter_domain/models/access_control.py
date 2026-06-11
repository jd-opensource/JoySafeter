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

    __tablename__ = "joysafeter_project_invitations"

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    inviter_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
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
        Index("ix_joysafeter_project_invitations_email_status", "email", "status"),
        # look up expired invitations
        Index("ix_joysafeter_project_invitations_expires_at", "expires_at"),
        # look up all invitations for a project
        Index("ix_joysafeter_project_invitations_project_id", "project_id"),
    )


class Permission(BaseModel):
    """Permission table (user permissions on entities)."""

    __tablename__ = "joysafeter_permissions"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
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
        Index("ix_joysafeter_permissions_user_id", "user_id"),
        Index("ix_joysafeter_permissions_entity", "entity_type", "entity_id"),
        Index("ix_joysafeter_permissions_user_entity_type", "user_id", "entity_type"),
        Index("ix_joysafeter_permissions_user_entity_permission", "user_id", "entity_type", "permission_type"),
        Index("ix_joysafeter_permissions_user_entity", "user_id", "entity_type", "entity_id"),
        UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_joysafeter_permissions_user_entity"),
    )
