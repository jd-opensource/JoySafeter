"""
Security Dept task model.

Stores execution metadata and summarized outputs for One Person Security Dept.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import AuthUser


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SecurityDeptTask(Base, TimestampMixin):
    """Task record for Security Dept asynchronous runs."""

    __tablename__ = "security_dept_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    scenario: Mapped[str] = mapped_column(String(50), nullable=False, default="pentest")
    profile: Mapped[str] = mapped_column(String(100), nullable=False, default="pentest_full_access_v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)

    target: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction_preview: Mapped[str] = mapped_column(String(500), nullable=False)
    selected_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    summary_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_structured: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    token_usage: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    execution_stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        Index("ix_security_dept_tasks_user_created", "user_id", "created_at"),
        Index("ix_security_dept_tasks_user_status", "user_id", "status"),
        Index("ix_security_dept_tasks_workspace_created", "workspace_id", "created_at"),
    )

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = utc_now()
        self.error_code = None
        self.error_message = None

    def mark_completed(
        self,
        *,
        summary_md: Optional[str],
        result_structured: Optional[dict[str, Any]],
        token_usage: Optional[dict[str, Any]],
        cost_usd: Optional[float],
    ) -> None:
        now = utc_now()
        self.status = "completed"
        self.summary_md = summary_md
        self.result_structured = result_structured
        self.token_usage = token_usage
        self.cost_usd = cost_usd
        self.finished_at = now
        if self.started_at is not None:
            self.duration_ms = int((now - self.started_at).total_seconds() * 1000)

    def mark_failed(self, *, error_code: str, error_message: str) -> None:
        now = utc_now()
        self.status = "failed"
        self.error_code = error_code
        self.error_message = error_message
        self.finished_at = now
        if self.started_at is not None:
            self.duration_ms = int((now - self.started_at).total_seconds() * 1000)

    def mark_cancelled(self) -> None:
        now = utc_now()
        self.status = "cancelled"
        self.finished_at = now
        if self.started_at is not None:
            self.duration_ms = int((now - self.started_at).total_seconds() * 1000)
