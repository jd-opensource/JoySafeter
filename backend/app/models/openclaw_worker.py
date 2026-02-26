"""
OpenClaw Worker Model
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.openclaw_task import OpenClawTask  # pragma: no cover


class OpenClawWorker(Base, TimestampMixin):
    """
    OpenClaw Worker 实例表

    每条记录对应一个 OpenClaw Worker 容器，
    由 JoySafeter 统一管理生命周期和负载均衡。
    """

    __tablename__ = "openclaw_worker"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), default="offline", nullable=False)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_tasks: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tasks: Mapped[list["OpenClawTask"]] = relationship(
        "OpenClawTask", back_populates="worker", lazy="selectin"
    )
