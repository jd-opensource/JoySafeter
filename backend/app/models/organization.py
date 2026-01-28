"""
组织/成员模型
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
    """与 drizzle text 主键兼容的字符串 UUID 生成器"""
    return str(uuid.uuid4())


class Organization(Base, TimestampMixin):
    """
    组织（对齐原始项目 drizzle `organization` 表）

    采用 text 主键以兼容 drizzle 定义。
    """

    __tablename__ = "organization"

    # 主键（使用 text 类型对齐原始项目）
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    logo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # NOTE: `metadata` 是 SQLAlchemy Declarative 的保留属性名，这里用 metadata_ 映射到列 metadata
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
    组织成员（对齐原始项目 drizzle `member` 表）

    采用 text 主键以兼容 drizzle 定义。
    """

    __tablename__ = "member"

    # 主键（使用 text 类型对齐原始项目）
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
