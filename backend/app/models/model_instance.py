"""
模型实例配置模型
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .model_provider import ModelProvider
    from .workspace import Workspace


class ModelInstance(BaseModel):
    """模型实例配置表"""

    __tablename__ = "model_instance"

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        comment="用户ID，如果为None则为全局模型记录",
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        comment="工作空间ID，如果为None则为用户级配置",
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_provider.id", ondelete="CASCADE"), nullable=False, comment="供应商ID"
    )
    model_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="模型名称，如 'gpt-4o', 'claude-3-5-sonnet'"
    )

    # 模型参数配置（JSON格式），如 {"temperature": 0.7, "max_tokens": 2000}
    model_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="模型参数配置")

    # 是否为默认模型
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否为默认模型")

    # 关系
    provider: Mapped["ModelProvider"] = relationship("ModelProvider", lazy="selectin")
    user: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")

    __table_args__ = (
        Index("model_instance_user_id_idx", "user_id"),
        Index("model_instance_workspace_id_idx", "workspace_id"),
        Index("model_instance_provider_id_idx", "provider_id"),
        Index("model_instance_user_provider_model_idx", "user_id", "provider_id", "model_name"),
        # 确保同一用户/工作空间对同一供应商+模型只有一条配置
        UniqueConstraint(
            "user_id", "workspace_id", "provider_id", "model_name", name="uq_model_instance_user_provider_model"
        ),
    )
