"""
OpenClaw Instance Model — per-user dedicated OpenClaw container.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import AuthUser


class OpenClawInstance(Base, TimestampMixin):
    """
    每用户独占一个 OpenClaw 容器实例。
    user_id 设置为 UNIQUE，保证一人一实例。
    """

    __tablename__ = "openclaw_instance"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gateway_port: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_token: Mapped[str] = mapped_column(String(512), nullable=False)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
