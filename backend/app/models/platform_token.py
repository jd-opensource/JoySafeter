"""Universal PlatformToken for API authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class PlatformToken(BaseModel):
    """API token with scoped permissions."""

    __tablename__ = "platform_tokens"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        Index("platform_tokens_user_idx", "user_id"),
        Index("platform_tokens_hash_idx", "token_hash"),
        Index("platform_tokens_active_idx", "is_active"),
    )
