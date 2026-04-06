"""
Model credential model
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .model_provider import ModelProvider
    from .workspace import Workspace


class ModelCredential(BaseModel):
    """Model credential table."""

    __tablename__ = "model_credential"

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        comment="user ID; NULL means global credential",
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        comment="workspace ID; NULL means user-level credential",
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_provider.id", ondelete="CASCADE"),
        nullable=False,
        comment="provider ID",
    )

    # encrypted credential (encrypted string)
    credentials: Mapped[str] = mapped_column(
        String(4096),
        nullable=False,
        comment="encrypted credential (base64-encoded)",
    )

    # credential validation state
    is_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="whether credential is valid"
    )
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="last validation time"
    )
    validation_error: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True, comment="validation error message"
    )

    # relationships
    provider: Mapped[Optional["ModelProvider"]] = relationship(
        "ModelProvider", back_populates="credentials", lazy="selectin"
    )
    user: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")

    __table_args__ = (
        Index("model_credential_user_id_idx", "user_id"),
        Index("model_credential_workspace_id_idx", "workspace_id"),
        Index("model_credential_provider_id_idx", "provider_id"),
        Index("model_credential_user_provider_idx", "user_id", "provider_id"),
        # ensure one credential per user/workspace per provider
        CheckConstraint("(workspace_id IS NULL) OR (workspace_id IS NOT NULL)", name="model_credential_scope_check"),
    )
