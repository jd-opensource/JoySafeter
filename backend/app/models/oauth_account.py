"""
OAuth account model

Store user-to-OAuth-provider bindings (GitHub, Google, custom OIDC, etc.).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import AuthUser  # pragma: no cover


def _generate_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid.uuid4())


class OAuthAccount(Base, TimestampMixin):
    """
    OAuth account association table.

    Store bindings between users and third-party OAuth providers:
    - Built-in providers: GitHub, Google, etc.
    - Custom OIDC providers: Keycloak, Authentik, etc.

    A user may bind multiple OAuth accounts (different providers).
    An OAuth account may only bind to one user.
    """

    __tablename__ = "oauth_account"
    __table_args__ = (
        # ensure the same provider account can only bind to one user
        Index("ix_oauth_account_provider_account", "provider", "provider_account_id", unique=True),
        # speed up lookups by user
        Index("ix_oauth_account_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_uuid,
    )

    # associated user ID
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # OAuth provider identifier (e.g. "github", "google", "keycloak")
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # provider-returned unique user identifier (e.g. GitHub user id)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # OAuth-returned email (optional; some providers may not return one)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # OAuth tokens (encrypted; used for subsequent API calls)
    # NOTE: access_token and refresh_token should be encrypted via CredentialEncryption
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # raw user info (JSON; for debugging and extensibility)
    raw_userinfo: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<OAuthAccount(id={self.id}, provider={self.provider}, user_id={self.user_id})>"
