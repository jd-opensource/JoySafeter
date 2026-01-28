"""
Auth 用户与会话表模型
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.organization import Organization  # pragma: no cover
    from app.models.workspace import Workspace, WorkspaceMember  # pragma: no cover


def _generate_str_id() -> str:
    """与 drizzle text 主键兼容的字符串 UUID 生成器。"""
    return str(uuid.uuid4())


class AuthUser(Base, TimestampMixin):
    """
    对应原始项目的 `user` 表。

    采用 text 主键以兼容 drizzle 定义，并保留基础时间戳字段。
    """

    __tablename__ = "user"

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 认证字段
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # token 字段
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verify_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verify_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_super_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 安全增强字段
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 关系
    sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    owned_workspaces: Mapped[List["Workspace"]] = relationship(
        "Workspace",
        back_populates="owner",
        foreign_keys="Workspace.owner_id",
    )
    workspace_memberships: Mapped[List["WorkspaceMember"]] = relationship(
        "WorkspaceMember",
        back_populates="user",
    )

    @property
    def full_name(self) -> str:
        """返回用户全名（兼容性属性）"""
        return self.name

    @property
    def is_superuser(self) -> bool:
        """兼容性属性：映射 is_super_user"""
        return self.is_super_user

    @is_superuser.setter
    def is_superuser(self, value: bool) -> None:
        """兼容性属性设置器"""
        self.is_super_user = value

    def is_locked(self) -> bool:
        """检查账户是否被锁定"""
        if not self.locked_until:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def unlock(self) -> None:
        """解锁账户"""
        self.locked_until = None
        self.lock_reason = None
        self.failed_login_attempts = 0


class AuthSession(Base, TimestampMixin):
    """
    对应原始项目的 `session` 表。

    完全对齐原始项目的 drizzle schema：
    - 表名: session
    - 字段: id, expires_at, token, created_at, updated_at, ip_address, user_agent, user_id, active_organization_id
    """

    __tablename__ = "session"
    __table_args__ = (
        Index("session_user_id_idx", "user_id"),
        Index("session_token_idx", "token", unique=True),
    )

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_str_id,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    active_organization_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("organization.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 安全增强字段
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 关系
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="sessions")
    active_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        lazy="selectin",
    )
