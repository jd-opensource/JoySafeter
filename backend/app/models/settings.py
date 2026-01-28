"""
环境变量/设置模型
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .workspace import Workspace


class Environment(BaseModel):
    """用户环境变量（一人一份）"""

    __tablename__ = "environment"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")


class WorkspaceEnvironment(BaseModel):
    """工作空间环境变量（一空间一份）"""

    __tablename__ = "workspace_environment"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")

    __table_args__ = (UniqueConstraint("workspace_id", name="workspace_environment_workspace_unique"),)


class Settings(BaseModel):
    """用户设置（一人一份）"""

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
