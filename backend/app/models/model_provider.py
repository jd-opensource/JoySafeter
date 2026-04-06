"""
Model provider model
"""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .model_credential import ModelCredential
    from .model_instance import ModelInstance


class ModelProvider(BaseModel):
    """Model provider table."""

    __tablename__ = "model_provider"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="unique provider identifier, e.g. 'openai', 'anthropic'"
    )
    display_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="display name, e.g. 'OpenAI', 'Anthropic'"
    )
    icon: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="icon URL")
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="provider description")

    # supported model type list, e.g. ["llm", "chat", "embedding", "rerank", "speech_to_text", "text_to_speech", "moderation"]
    supported_model_types: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, comment="supported model type list"
    )

    # credential form rules (JSON Schema format)
    credential_schema: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="credential form rules defining required fields"
    )

    # configuration rules (parameter rules)
    config_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="model parameter config rules")

    # whether this is a template (used to create custom providers)
    is_template: Mapped[bool] = mapped_column(
        default=False, nullable=False, comment="whether this is a template (for creating custom providers)"
    )

    # template name (if provider_type is custom, references the template name)
    template_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="referenced template name")

    # provider type: system, custom
    provider_type: Mapped[str] = mapped_column(
        String(50), default="system", nullable=False, comment="provider type: system, custom"
    )

    # whether enabled
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False, comment="whether this provider is enabled")

    # provider-level default parameters (JSON), e.g. {"temperature": 0.7, "max_tokens": 2000}
    default_parameters: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}", comment="provider-level default parameters"
    )

    # relationships
    credentials: Mapped[list["ModelCredential"]] = relationship(
        "ModelCredential",
        back_populates="provider",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    model_instances: Mapped[list["ModelInstance"]] = relationship(
        "ModelInstance",
        back_populates="provider",
        lazy="noload",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("model_provider_name_idx", "name"),
        Index("model_provider_enabled_idx", "is_enabled"),
    )
