"""
模型使用日志模型
"""

from typing import Optional

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ModelUsageLog(BaseModel):
    """模型使用日志表"""

    __tablename__ = "model_usage_log"

    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="供应商名称")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="模型名称")
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="模型类型")
    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="用户ID",
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="输入token数")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="输出token数")
    total_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="总耗时(ms)")
    ttft_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="首token时间(ms)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success", comment="状态: success/error")
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True, comment="错误信息")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="来源: chat/playground")

    __table_args__ = (
        Index("model_usage_log_created_at_idx", "created_at"),
        Index("model_usage_log_provider_model_idx", "provider_name", "model_name"),
        Index("model_usage_log_created_provider_model_idx", "created_at", "provider_name", "model_name"),
    )
