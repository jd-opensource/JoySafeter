import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_domain.models.base import JoySafeterBaseModel


class JoySafeterVault(JoySafeterBaseModel):
    __tablename__ = "joysafeter_vaults"
    __table_args__ = (
        UniqueConstraint("name", name="idx_cv_name"),
        Index("idx_cv_project", "project_id"),
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

    vault_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
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
