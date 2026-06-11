"""
User Sandbox Model
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base
from app.joysafeter_domain.models.base import JoySafeterBaseModel, TimestampMixin
from app.joysafeter_domain.models.enums import InstanceStatus

if TYPE_CHECKING:
    from app.joysafeter_domain.models.auth import AuthUser  # pragma: no cover


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
        String(255), ForeignKey("joysafeter_users.id", ondelete="CASCADE"), nullable=False, unique=True
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


# ---------------------------------------------------------------------------
# JoySafeter Sandbox model
# ---------------------------------------------------------------------------


class JoySafeterSandbox(JoySafeterBaseModel):
    __tablename__ = "joysafeter_sandboxes"
    __table_args__ = (
        Index("idx_csb_status", "status"),
        Index(
            "idx_csb_pool",
            "created_at",
            postgresql_where="status = 'pooled'",
        ),
        Index(
            "idx_csb_session",
            "chat_session_id",
            postgresql_where="chat_session_id IS NOT NULL",
        ),
        Index(
            "idx_csb_active_session_unique",
            "chat_session_id",
            unique=True,
            postgresql_where=(
                "chat_session_id IS NOT NULL AND destroyed_at IS NULL AND "
                "status IN ('creating', 'provisioning', 'idle', 'running', "
                "'stopped', 'error')"
            ),
        ),
        Index("idx_csb_project", "project_id"),
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True, index=True,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="docker")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="creating")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    image: Mapped[str] = mapped_column(Text, nullable=False)
    last_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    destroyed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    workspace_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
