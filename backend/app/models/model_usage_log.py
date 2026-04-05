"""
Model usage log model
"""

from typing import Optional

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ModelUsageLog(BaseModel):
    """Model usage log table."""

    __tablename__ = "model_usage_log"

    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="provider name")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="model name")
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="model type")
    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="user ID",
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="input token count")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="output token count")
    total_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="total time (ms)")
    ttft_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="time to first token (ms)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success", comment="status: success/error")
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True, comment="error message")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="source: chat/playground")

    __table_args__ = (
        Index("model_usage_log_created_at_idx", "created_at"),
        Index("model_usage_log_provider_model_idx", "provider_name", "model_name"),
        Index("model_usage_log_created_provider_model_idx", "created_at", "provider_name", "model_name"),
    )
