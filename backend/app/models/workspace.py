"""
Workspace models
"""

import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from .auth import AuthUser


class WorkspaceStatus(str, PyEnum):
    """Workspace status."""

    active = "active"
    deprecated = "deprecated"
    archived = "archived"


class WorkspaceType(str, PyEnum):
    """Workspace type."""

    personal = "personal"  # personal workspace
    team = "team"  # team workspace


class WorkspaceMemberRole(str, PyEnum):
    """Workspace member role."""

    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class Workspace(BaseModel, SoftDeleteMixin):
    """Workspace."""

    __tablename__ = "workspaces"

    # basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[WorkspaceStatus] = mapped_column(
        Enum(WorkspaceStatus, name="workspacestatus", create_type=False),
        nullable=False,
        default=WorkspaceStatus.active,
    )
    type: Mapped[WorkspaceType] = mapped_column(
        Enum(WorkspaceType, name="workspacetype", create_type=False),
        nullable=False,
        default=WorkspaceType.personal,
    )
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # owner (text type to match User.id)
    owner_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # relationships
    owner: Mapped["AuthUser"] = relationship(
        "AuthUser",
        back_populates="owned_workspaces",
        foreign_keys=[owner_id],
    )
    members: Mapped[List["WorkspaceMember"]] = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class WorkspaceMember(BaseModel):
    """Workspace member."""

    __tablename__ = "workspace_members"

    # associations
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

    # role
    role: Mapped[WorkspaceMemberRole] = mapped_column(
        Enum(WorkspaceMemberRole, name="workspacememberrole", create_type=False),
        nullable=False,
        default=WorkspaceMemberRole.member,
    )

    # relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="members",
    )
    user: Mapped["AuthUser"] = relationship(
        "AuthUser",
        back_populates="workspace_memberships",
    )


class WorkspaceFolder(BaseModel, SoftDeleteMixin):
    """Workspace folder."""

    __tablename__ = "workspace_folder"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_folder.id", ondelete="SET NULL"),
        nullable=True,
    )

    color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default="#6B7280")
    is_expanded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    parent: Mapped[Optional["WorkspaceFolder"]] = relationship(
        "WorkspaceFolder",
        remote_side="WorkspaceFolder.id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("workspace_folder_user_idx", "user_id"),
        Index("workspace_folder_workspace_parent_idx", "workspace_id", "parent_id"),
        Index("workspace_folder_parent_sort_idx", "parent_id", "sort_order"),
        Index("workspace_folder_deleted_at_idx", "deleted_at"),
    )
