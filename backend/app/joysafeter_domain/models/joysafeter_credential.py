from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel, TimestampMixin
from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import (
    CredentialGroupId,
    CredentialId,
    EntityIdType,
    SessionId,
)


class JoySafeterCredential(JoySafeterBaseModel):
    __tablename__ = "joysafeter_credentials"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'model' AND provider IS NOT NULL AND protocol IS NOT NULL "
            "AND mcp_server_url IS NULL AND normalized_mcp_server_url IS NULL "
            "AND credential_type IS NULL AND oauth_config IS NULL AND group_id IS NULL) OR "
            "(kind = 'mcp' AND mcp_server_url IS NOT NULL "
            "AND normalized_mcp_server_url IS NOT NULL AND credential_type IS NOT NULL "
            "AND group_id IS NOT NULL "
            "AND provider IS NULL AND protocol IS NULL AND is_default = false) OR "
            "(kind = 'service' AND provider IS NULL AND protocol IS NULL "
            "AND mcp_server_url IS NULL AND normalized_mcp_server_url IS NULL "
            "AND credential_type IS NULL AND oauth_config IS NULL "
            "AND group_id IS NULL AND is_default = false)",
            name="kind_identity",
        ),
        Index(
            "uq_credentials_project_kind_name",
            "project_id",
            "kind",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_credentials_default_protocol",
            "project_id",
            "protocol",
            unique=True,
            postgresql_where=text(
                "is_default = true AND kind = 'model' AND archived_at IS NULL AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "is_default = true AND kind = 'model' AND archived_at IS NULL AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_credentials_group_url",
            "group_id",
            "normalized_mcp_server_url",
            unique=True,
            postgresql_where=text("kind = 'mcp' AND deleted_at IS NULL"),
            sqlite_where=text("kind = 'mcp' AND deleted_at IS NULL"),
        ),
        Index("ix_joysafeter_credentials_project_id", "project_id"),
        Index("ix_joysafeter_credentials_group_id", "group_id"),
        # Composite FK enforcing project isolation for credential groups. Targets
        # the UNIQUE(id, project_id) declared on joysafeter_credential_groups.
        ForeignKeyConstraint(
            ["group_id", "project_id"],
            [
                "joysafeter_credential_groups.id",
                "joysafeter_credential_groups.project_id",
            ],
            name="fk_credentials_group_project",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[CredentialId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(CredentialId), primary_key=True, default=CredentialId.new
    )

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    protocol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    mcp_server_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_mcp_server_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credential_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    group_id: Mapped[Optional[CredentialGroupId]] = mapped_column(
        EntityIdType(CredentialGroupId), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterCredentialGroup(JoySafeterBaseModel):
    __tablename__ = "joysafeter_credential_groups"
    __table_args__ = (
        Index(
            "uq_credential_groups_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        UniqueConstraint("id", "project_id", name="uq_credential_groups_id_project"),
        Index("ix_joysafeter_credential_groups_project_id", "project_id"),
    )

    id: Mapped[CredentialGroupId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(CredentialGroupId), primary_key=True, default=CredentialGroupId.new
    )

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterSessionCredentialGroup(Base, TimestampMixin):
    __tablename__ = "joysafeter_session_credential_groups"

    # Association row with a true composite PK; no surrogate id column, so it
    # extends Base + TimestampMixin (rather than JoySafeterBaseModel, which would
    # inject an `id` primary key).
    session_id: Mapped[SessionId] = mapped_column(
        EntityIdType(SessionId),
        ForeignKey("joysafeter_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    credential_group_id: Mapped[CredentialGroupId] = mapped_column(
        EntityIdType(CredentialGroupId),
        ForeignKey("joysafeter_credential_groups.id", ondelete="RESTRICT"),
        primary_key=True,
    )
