from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_domain.models.base import JoySafeterBaseModel
from app.joysafeter_shared.ids import CredentialId, EntityIdType, VaultId


class JoySafeterVault(JoySafeterBaseModel):
    __tablename__ = "joysafeter_vaults"
    __table_args__ = (
        Index(
            "uq_joysafeter_vaults_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_joysafeter_vaults_global_name",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NULL AND deleted_at IS NULL"),
        ),
        Index("idx_cv_project", "project_id"),
    )

    id: Mapped[VaultId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(VaultId), primary_key=True, default=VaultId.new
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    credentials: Mapped[list["JoySafeterVaultCredential"]] = relationship(back_populates="vault", lazy="selectin")


class JoySafeterVaultCredential(JoySafeterBaseModel):
    __tablename__ = "joysafeter_vault_credentials"
    __table_args__ = (
        UniqueConstraint(
            "vault_id",
            "mcp_server_url",
            name="idx_cvc_url",
        ),
    )

    id: Mapped[CredentialId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(CredentialId), primary_key=True, default=CredentialId.new
    )

    vault_id: Mapped[VaultId] = mapped_column(
        EntityIdType(VaultId),
        ForeignKey("joysafeter_vaults.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    credential_type: Mapped[str] = mapped_column(Text, nullable=False, default="static_bearer")
    mcp_server_url: Mapped[str] = mapped_column(Text, nullable=False)
    token_value: Mapped[str] = mapped_column(Text, nullable=False)
    oauth_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    vault: Mapped["JoySafeterVault"] = relationship(back_populates="credentials")
