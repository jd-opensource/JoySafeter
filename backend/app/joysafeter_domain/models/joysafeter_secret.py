from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel
from app.joysafeter_shared.ids import EntityIdType, SecretId


class JoySafeterSecret(JoySafeterBaseModel):
    __tablename__ = "joysafeter_secrets"
    __table_args__ = (
        Index(
            "uq_joysafeter_secrets_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_joysafeter_secrets_global_name",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_joysafeter_secrets_project_protocol_default",
            "project_id",
            "protocol",
            unique=True,
            postgresql_where=text(
                "project_id IS NOT NULL AND kind = 'llm' AND is_default = true AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "project_id IS NOT NULL AND kind = 'llm' AND is_default = true AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_joysafeter_secrets_global_protocol_default",
            "protocol",
            unique=True,
            postgresql_where=text(
                "project_id IS NULL AND kind = 'llm' AND is_default = true AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "project_id IS NULL AND kind = 'llm' AND is_default = true AND deleted_at IS NULL"
            ),
        ),
        CheckConstraint(
            "(kind = 'llm' AND provider IS NOT NULL AND protocol IS NOT NULL) OR "
            "(kind = 'generic' AND provider IS NULL AND protocol IS NULL AND is_default = false)",
            name="kind_identity",
        ),
    )

    id: Mapped[SecretId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(SecretId), primary_key=True, default=SecretId.new
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    protocol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
