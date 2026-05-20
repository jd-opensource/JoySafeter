import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ConductorVault(BaseModel):
    __tablename__ = "conductor_vaults"
    __table_args__ = (
        UniqueConstraint("name", name="idx_cv_name"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    credentials: Mapped[list["ConductorVaultCredential"]] = relationship(
        back_populates="vault", lazy="selectin"
    )


class ConductorVaultCredential(BaseModel):
    __tablename__ = "conductor_vault_credentials"
    __table_args__ = (
        UniqueConstraint(
            "vault_id",
            "mcp_server_url",
            name="idx_cvc_url",
        ),
    )

    vault_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_vaults.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    credential_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="static_bearer"
    )
    mcp_server_url: Mapped[str] = mapped_column(Text, nullable=False)
    token_value: Mapped[str] = mapped_column(Text, nullable=False)
    oauth_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    vault: Mapped["ConductorVault"] = relationship(back_populates="credentials")
