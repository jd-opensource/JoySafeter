"""
Project model — scopes joysafeter resources within an organization.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import OrganizationId, ProjectId, ProjectMemberId, UserId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

from .base import TimestampMixin

if TYPE_CHECKING:
    from .joysafeter_auth import AuthUser
    from .organization import Organization


class Project(Base, TimestampMixin):
    """
    A project within an organization.

    Projects scope joysafeter resources (agents, sessions, etc.) and provide
    per-project API key isolation.
    """

    __tablename__ = "joysafeter_organization_projects"

    id: Mapped[ProjectId] = mapped_column(EntityIdType(ProjectId), primary_key=True)
    org_id: Mapped[OrganizationId] = mapped_column(
        EntityIdType(OrganizationId),
        ForeignKey("joysafeter_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[Optional[UserId]] = mapped_column(
        EntityIdType(UserId),
        ForeignKey("joysafeter_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    triggers_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Per-project concurrent-task admission override. NULL => use the global
    # default (settings.max_concurrent_per_project). Lets paid/trusted tenants
    # carry a higher ceiling without a code change.
    max_concurrent_tasks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Per-project sandbox resource overrides. NULL => use the global default
    # (settings.sandbox_cpu / sandbox_memory_mb). max_cpu is in cores (e.g. 2.0),
    # max_memory_mb in MiB. Applied per-field, so a project may override only one.
    max_cpu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_memory_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="projects")

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_joysafeter_organization_projects_org_slug"),
        UniqueConstraint("id", "org_id", name="uq_joysafeter_organization_projects_id_org"),
        Index("ix_joysafeter_organization_projects_org_id", "org_id"),
        Index("ix_joysafeter_organization_projects_created_by_user_id", "created_by_user_id"),
        Index(
            "uq_joysafeter_organization_projects_active_default",
            "org_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE AND archived_at IS NULL"),
            sqlite_where=text("is_default = 1 AND archived_at IS NULL"),
        ),
    )


class ProjectMember(Base, TimestampMixin):
    """Membership row binding a user to a specific project.

    A row grants a non-super-user access to a project; org owner/admin reach
    every project without one. ``role`` is the authoritative per-project
    capability for non-super-users (``admin`` / ``editor`` / ``viewer``; see
    ``ProjectRole``). The ``effective_project_capability`` function derives
    read/write/admin solely from this value.
    """

    __tablename__ = "joysafeter_project_members"

    id: Mapped[ProjectMemberId] = mapped_column(EntityIdType(ProjectMemberId), primary_key=True)
    project_id: Mapped[ProjectId] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UserId] = mapped_column(
        EntityIdType(UserId),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project capability: admin / editor / viewer (see ProjectRole).
    # Defaults to viewer (least privilege) if a grant path ever omits the role.
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")

    # relationships
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            name="uq_joysafeter_project_members_project_user",
        ),
        Index("ix_joysafeter_project_members_project_id", "project_id"),
        Index("ix_joysafeter_project_members_user_id", "user_id"),
    )
