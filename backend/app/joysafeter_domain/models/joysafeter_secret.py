from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
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
    provider: Mapped[str] = mapped_column(String(64), nullable=False, server_default="custom")
    protocol: Mapped[str] = mapped_column(String(64), nullable=False, server_default="custom")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
