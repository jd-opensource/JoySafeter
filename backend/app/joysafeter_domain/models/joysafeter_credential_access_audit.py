from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid_utils import uuid7

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import CredentialId, EntityIdType, SessionId, TaskId


class JoySafeterCredentialAccessAudit(Base):
    __tablename__ = "joysafeter_credential_access_audits"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="credential_access_audit_result",
        ),
        CheckConstraint(
            "generation IS NULL OR generation >= 0",
            name="credential_access_audit_generation",
        ),
        CheckConstraint(
            "jsonb_typeof(field_names) = 'array'",
            name="credential_access_audit_field_names",
        ),
        Index(
            "uq_credential_access_audits_runtime_success",
            "session_id",
            "generation",
            "credential_id",
            "usage",
            "consumer_type",
            "consumer_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("result = 'success' AND session_id IS NOT NULL AND generation IS NOT NULL"),
        ),
        Index("ix_credential_access_audits_project_created", "project_id", "created_at"),
        Index("ix_credential_access_audits_credential_created", "credential_id", "created_at"),
        Index("ix_credential_access_audits_session_generation", "session_id", "generation"),
        Index("ix_credential_access_audits_result_created", "result", "created_at"),
        Index(
            "ix_credential_access_audits_principal_created",
            "principal_type",
            "principal_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=lambda: uuid7())
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_id: Mapped[CredentialId] = mapped_column(EntityIdType(CredentialId), nullable=False)
    credential_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    usage: Mapped[str] = mapped_column(String(64), nullable=False)
    consumer_type: Mapped[str] = mapped_column(String(64), nullable=False)
    consumer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    principal_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    principal_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    session_id: Mapped[Optional[SessionId]] = mapped_column(EntityIdType(SessionId), nullable=True)
    task_id: Mapped[Optional[TaskId]] = mapped_column(EntityIdType(TaskId), nullable=True)
    generation: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    field_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
