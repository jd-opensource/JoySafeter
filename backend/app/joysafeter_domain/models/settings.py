"""
Environment variable and settings models
"""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class Environment(BaseModel):
    """User environment variables (one per user)."""

    __tablename__ = "environment"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")


class ProjectEnvironment(BaseModel):
    """Project-level environment variables (stored as encrypted JSON)."""

    __tablename__ = "project_environment"

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("project_id", name="project_environment_project_unique"),)


class Settings(BaseModel):
    """User settings (one per user)."""

    __tablename__ = "settings"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # General settings
    theme: Mapped[str] = mapped_column(String(50), nullable=False, default="system")
    auto_connect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_pan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    console_expanded_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Privacy settings
    telemetry_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Email preferences
    email_preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Billing usage notifications preference
    billing_usage_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # UI preferences
    show_floating_controls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_training_controls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    super_user_mode_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Notification preferences
    error_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Copilot preferences - maps model_id to enabled/disabled boolean
    copilot_enabled_models: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (Index("settings_user_id_idx", "user_id"),)
