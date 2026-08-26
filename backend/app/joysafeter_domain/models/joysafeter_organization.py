"""
Organization and member models
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import OrganizationId, OrganizationMemberId, UserId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

from .base import TimestampMixin

if TYPE_CHECKING:
    from .joysafeter_auth import AuthUser
    from .joysafeter_project import Project


class Organization(Base, TimestampMixin):
    """Organization aggregate root."""

    __tablename__ = "joysafeter_organizations"

    id: Mapped[OrganizationId] = mapped_column(EntityIdType(OrganizationId), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    logo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # NOTE: `metadata` is a reserved attribute name in SQLAlchemy Declarative; use metadata_ mapped to the metadata column
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    project_creation_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="admins_only",
        server_default="admins_only",
    )

    org_usage_limit: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    storage_used_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    departed_member_usage: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)

    members: Mapped[List["Member"]] = relationship(
        "Member",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    projects: Mapped[List["Project"]] = relationship(
        "Project",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class Member(Base, TimestampMixin):
    """Organization membership row."""

    __tablename__ = "joysafeter_organization_members"

    id: Mapped[OrganizationMemberId] = mapped_column(EntityIdType(OrganizationMemberId), primary_key=True)

    user_id: Mapped[UserId] = mapped_column(
        EntityIdType(UserId),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[OrganizationId] = mapped_column(
        EntityIdType(OrganizationId),
        ForeignKey("joysafeter_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")

    __table_args__ = (
        Index("ix_joysafeter_organization_members_user_id", "user_id"),
        Index("ix_joysafeter_organization_members_organization_id", "organization_id"),
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_joysafeter_organization_members_org_user",
        ),
    )
