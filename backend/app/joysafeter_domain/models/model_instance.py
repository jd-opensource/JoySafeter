"""
Model instance configuration model
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, ForeignKey, Index, String  # String kept for user_id/model_name columns
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .model_provider import ModelProvider


class ModelInstance(BaseModel):
    """Model instance configuration table."""

    __tablename__ = "model_instance"

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=True,
        comment="user ID; NULL means global model record",
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="SET NULL"), nullable=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_provider.id", ondelete="CASCADE"),
        nullable=False,
        comment="provider ID",
    )
    model_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="model name, e.g. 'gpt-4o', 'claude-3-5-sonnet'"
    )

    # model parameter configuration (JSON), e.g. {"temperature": 0.7, "max_tokens": 2000}
    model_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="model parameter config")

    # relationships
    provider: Mapped[Optional["ModelProvider"]] = relationship(
        "ModelProvider", back_populates="model_instances", lazy="selectin"
    )
    user: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")

    @property
    def resolved_provider_name(self) -> str:
        """Provider name, resolved through FK relationship."""
        return self.provider.name if self.provider else ""

    @property
    def resolved_implementation_name(self) -> str:
        """Implementation name for factory lookup (template_name or provider name)."""
        if self.provider:
            return self.provider.template_name or self.provider.name
        return ""

    __table_args__ = (
        Index("model_instance_user_id_idx", "user_id"),
        Index("model_instance_provider_id_idx", "provider_id"),
        Index("model_instance_user_provider_model_idx", "user_id", "provider_id", "model_name"),
    )
