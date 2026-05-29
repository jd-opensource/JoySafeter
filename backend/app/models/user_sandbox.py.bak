"""
User Sandbox Model
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import InstanceStatus

if TYPE_CHECKING:
    from app.models.auth import AuthUser  # pragma: no cover


class UserSandbox(Base, TimestampMixin):
    """
    User sandbox record table.

    Store per-user sandbox instance info including container ID, status, and resource limits.
    Each user may have only one active sandbox record at a time.
    """

    __tablename__ = "user_sandbox"

    # sandbox ID (typically associated with user_id, or an independent UUID)
    id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # associated user
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Docker container info
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default=InstanceStatus.PENDING, nullable=False)

    # image and runtime configuration
    image: Mapped[str] = mapped_column(String(255), default="python:3.12-slim", nullable=False)
    runtime: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # runtime state tracking
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # resource limit configuration
    cpu_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # CPU cores, e.g. 1.0
    memory_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # memory in MB, e.g. 512
    idle_timeout: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)  # idle timeout in seconds

    # relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="sandbox")
