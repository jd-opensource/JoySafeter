from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import ProjectId, TaskId, UserId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

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
        CheckConstraint(
            "state IN ('captured', 'resolving', 'issued', 'expired', 'discarded')",
            name="ck_task_identity_resolution_state",
        ),
        CheckConstraint(
            "(state = 'resolving' AND resolution_id IS NOT NULL AND resolution_expires_at IS NOT NULL) "
            "OR (state <> 'resolving' AND resolution_id IS NULL AND resolution_expires_at IS NULL)",
            name="ck_task_identity_resolution_claim",
        ),
        CheckConstraint(
            "(state IN ('captured', 'resolving') AND encrypted_credential IS NOT NULL "
            "AND consumed_at IS NULL AND erased_at IS NULL) "
            "OR (state = 'issued' AND encrypted_credential IS NULL "
            "AND consumed_at IS NOT NULL AND erased_at IS NOT NULL) "
            "OR (state IN ('expired', 'discarded') AND encrypted_credential IS NULL "
            "AND consumed_at IS NULL AND erased_at IS NOT NULL)",
            name="ck_task_identity_resolution_material",
        ),
        Index("ix_task_identity_project_expires", "project_id", "expires_at"),
        Index("ix_task_identity_user", "user_id"),
        Index(
            "uq_task_identity_auth_code_fingerprint",
            "credential_fingerprint",
            unique=True,
            postgresql_where=text("credential_kind = 'auth_code'"),
        ),
        Index(
            "ix_task_identity_pending_expiry",
            "expires_at",
            "task_id",
            postgresql_where=text("encrypted_credential IS NOT NULL"),
        ),
        Index(
            "ix_task_identity_resolution_expiry",
            "resolution_expires_at",
            "task_id",
            postgresql_where=text("state = 'resolving'"),
        ),
    )

    task_id: Mapped[TaskId] = mapped_column(
        EntityIdType(TaskId),
        ForeignKey("joysafeter_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[Optional[ProjectId]] = mapped_column(EntityIdType(ProjectId), nullable=True)
    user_id: Mapped[UserId] = mapped_column(EntityIdType(UserId), nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credential_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    encrypted_credential: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'captured'"))
    resolution_id: Mapped[Optional[UUID]] = mapped_column(Uuid, nullable=True)
    resolution_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    erased_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
