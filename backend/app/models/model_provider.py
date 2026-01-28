"""
模型供应商模型
"""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .model_credential import ModelCredential


class ModelProvider(BaseModel):
    """模型供应商表"""

    __tablename__ = "model_provider"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="供应商唯一标识，如 'openai', 'anthropic'"
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="显示名称，如 'OpenAI', 'Anthropic'")
    icon: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="图标URL")
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="供应商描述")

    # 支持的模型类型列表，如 ["llm", "chat", "embedding", "rerank", "speech_to_text", "text_to_speech", "moderation"]
    supported_model_types: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=list, comment="支持的模型类型列表"
    )

    # 凭据表单规则（JSON Schema格式）
    credential_schema: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="凭据表单规则，定义需要哪些字段"
    )

    # 配置规则（参数规则）
    config_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="模型参数配置规则")

    # 是否启用
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False, comment="是否启用该供应商")

    # 关系
    credentials: Mapped[list["ModelCredential"]] = relationship(
        "ModelCredential", back_populates="provider", lazy="selectin"
    )

    __table_args__ = (
        Index("model_provider_name_idx", "name"),
        Index("model_provider_enabled_idx", "is_enabled"),
    )
