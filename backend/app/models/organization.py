"""
Organization and member models
"""

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from .base import TimestampMixin

if TYPE_CHECKING:
    from .auth import AuthUser


def _generate_str_id() -> str:
    """Generate a string UUID compatible with drizzle text primary keys."""
    return str(uuid.uuid4())


class Organization(Base, TimestampMixin):
    """
    Organization (aligned with the original drizzle `organization` table).

    Use text primary key for drizzle compatibility.
    """

    __tablename__ = "organization"

    # primary key (text type to match original project)
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    logo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # NOTE: `metadata` is a reserved attribute name in SQLAlchemy Declarative; use metadata_ mapped to the metadata column
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

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


class Member(Base, TimestampMixin):
    """
    Organization member (aligned with the original drizzle `member` table).

    Use text primary key for drizzle compatibility.
    """

    __tablename__ = "member"

    # primary key (text type to match original project)
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")

    __table_args__ = (
        Index("member_user_id_idx", "user_id"),
        Index("member_organization_id_idx", "organization_id"),
    )
