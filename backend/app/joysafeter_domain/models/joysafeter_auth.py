"""
Auth user and session table models
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_domain.models.base import TimestampMixin
from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import AuthSessionId, OrganizationId, UserId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

if TYPE_CHECKING:
    from app.joysafeter_domain.models.joysafeter_oauth_account import OAuthAccount  # pragma: no cover
    from app.joysafeter_domain.models.joysafeter_organization import Organization  # pragma: no cover


class AuthUser(Base, TimestampMixin):
    """Authenticated platform user."""

    __tablename__ = "joysafeter_users"

    id: Mapped[UserId] = mapped_column(EntityIdType(UserId), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # auth fields
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # token fields
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verify_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verify_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_super_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # security fields
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # relationships
    sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def is_locked(self) -> bool:
        """Check whether the account is locked."""
        if not self.locked_until:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def unlock(self) -> None:
        """Unlock the account."""
        self.locked_until = None
        self.lock_reason = None
        self.failed_login_attempts = 0


class AuthSession(Base, TimestampMixin):
    """Durable authenticated browser session."""

    __tablename__ = "joysafeter_auth_sessions"
    __table_args__ = (
        Index("ix_joysafeter_auth_sessions_user_id", "user_id"),
        Index("ix_joysafeter_auth_sessions_token", "token", unique=True),
        Index("idx_joysafeter_auth_sessions_expires", "expires_at"),
        Index("idx_joysafeter_auth_sessions_last_activity", "last_activity_at"),
    )

    id: Mapped[AuthSessionId] = mapped_column(EntityIdType(AuthSessionId), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    user_id: Mapped[UserId] = mapped_column(
        EntityIdType(UserId),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    active_organization_id: Mapped[Optional[OrganizationId]] = mapped_column(
        EntityIdType(OrganizationId),
        ForeignKey("joysafeter_organizations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # security fields
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # relationships
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="sessions")
    active_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        lazy="selectin",
    )
