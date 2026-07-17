"""
Project model — scopes joysafeter resources within an organization.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .joysafeter_auth import AuthUser
    from .organization import Organization


def _generate_str_id() -> str:
    """Generate a string UUID compatible with drizzle text primary keys."""
    return str(uuid.uuid4())


class Project(Base, TimestampMixin):
    """
    A project within an organization.

    Projects scope joysafeter resources (agents, sessions, etc.) and provide
    per-project API key isolation.  Uses text primary key for drizzle compatibility.
    """

    __tablename__ = "joysafeter_organization_projects"

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )
    org_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
        Index("ix_joysafeter_organization_projects_org_id", "org_id"),
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

    P2.8 introduces this table so the four-tier ``visibility`` model can
    actually distinguish ``project`` from ``organization``:

      - ``project`` skill → only members of THAT project can see / load
      - ``organization`` skill → anyone in the parent org can

    Before P2.8 both tiers collapsed to "is the user in the same org",
    making ``project`` indistinguishable from ``organization`` at the
    permission layer. The migration that creates this table
    (``20260625_000007_project_members``) backfills every existing org
    member into the org's default project so legacy data keeps working
    without the user explicitly granting per-project access.

    ``role`` is the authoritative per-project capability for non-super-users
    (``admin`` / ``editor`` / ``viewer``; see ``ProjectRole``). The
    ``effective_project_capability`` function derives read/write/admin
    solely from this value, so it is no longer free-form or presence-only.
    Legacy values (``owner`` / ``developer`` / ``member``) are normalized
    both by a data migration (``20260717_000014_normalize_project_member_roles``)
    and at runtime by ``ProjectRole.normalize``.
    """

    __tablename__ = "joysafeter_project_members"

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )
    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project capability: admin / editor / viewer (see ProjectRole).
    # Legacy values are normalized by ProjectRole.normalize at runtime.
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")

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
