"""
Project model — scopes joysafeter resources within an organization.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
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
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="projects"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_joysafeter_organization_projects_org_slug"),
        Index("ix_joysafeter_organization_projects_org_id", "org_id"),
    )
