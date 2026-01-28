"""
模型凭据模型
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
    """模型凭据表"""

    __tablename__ = "model_credential"

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        comment="用户ID，如果为None则为全局认证信息",
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        comment="工作空间ID，如果为None则为用户级凭据",
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_provider.id", ondelete="CASCADE"), nullable=False, comment="供应商ID"
    )

    # 加密存储的凭据（加密字符串）
    credentials: Mapped[str] = mapped_column(
        String(4096),
        nullable=False,
        comment="加密存储的凭据（base64编码）",
    )

    # 凭据验证状态
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="凭据是否有效")
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后验证时间"
    )
    validation_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="验证错误信息")

    # 关系
    provider: Mapped["ModelProvider"] = relationship("ModelProvider", back_populates="credentials", lazy="selectin")
    user: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")

    __table_args__ = (
        Index("model_credential_user_id_idx", "user_id"),
        Index("model_credential_workspace_id_idx", "workspace_id"),
        Index("model_credential_provider_id_idx", "provider_id"),
        Index("model_credential_user_provider_idx", "user_id", "provider_id"),
        # 确保同一用户/工作空间对同一供应商只有一条凭据
        CheckConstraint("(workspace_id IS NULL) OR (workspace_id IS NOT NULL)", name="model_credential_scope_check"),
    )
