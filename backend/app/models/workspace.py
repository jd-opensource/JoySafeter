"""
Workspace models
"""

import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from .auth import AuthUser


class WorkspaceStatus(str, PyEnum):
    """Workspace status."""

    active = "active"
    deprecated = "deprecated"  # retained for DB backward compatibility
    archived = "archived"  # retained for DB backward compatibility


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

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)
