"""
OpenClaw Task Model
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import AuthUser
    from app.models.openclaw_instance import OpenClawInstance


class OpenClawTask(Base, TimestampMixin):
    """
    OpenClaw 任务表

    记录用户提交的任务、分配到的 Instance、执行状态和输出。
    通过 Redis Pub/Sub 频道实时推送执行输出。
    """

    __tablename__ = "openclaw_task"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instance_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("openclaw_instance.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redis_channel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    instance: Mapped[Optional["OpenClawInstance"]] = relationship(
        "OpenClawInstance", back_populates="tasks", lazy="selectin"
    )
