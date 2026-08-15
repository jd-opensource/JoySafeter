from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import EntityIdType, TaskId

from .base import TimestampMixin


class JoySafeterTaskIdentityContext(Base, TimestampMixin):
    __tablename__ = "joysafeter_task_identity_contexts"
    __table_args__ = (
        CheckConstraint(
            "credential_kind IN ('auth_code', 'identity_token')",
            name="ck_task_identity_credential_kind",
        ),
        CheckConstraint(
            "(credential_kind = 'auth_code' AND credential_fingerprint IS NOT NULL) "
            "OR (credential_kind = 'identity_token' AND credential_fingerprint IS NULL)",
            name="ck_task_identity_fingerprint_kind",
        ),
        Index("ix_task_identity_project_expires", "project_id", "expires_at"),
        Index("ix_task_identity_user", "user_id"),
        Index(
            "uq_task_identity_auth_code_fingerprint",
            "credential_fingerprint",
            unique=True,
            postgresql_where=text("credential_kind = 'auth_code'"),
        ),
    )

    task_id: Mapped[TaskId] = mapped_column(
        EntityIdType(TaskId),
        ForeignKey("joysafeter_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credential_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    encrypted_credential: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
