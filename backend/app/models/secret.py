import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ConductorBaseModel


class ConductorSecret(ConductorBaseModel):
    __tablename__ = "conductor_secrets"
    __table_args__ = (
        UniqueConstraint("name", name="idx_cs_name_unique"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
