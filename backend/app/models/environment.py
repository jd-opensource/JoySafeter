import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ConductorBaseModel


class ConductorEnvironment(ConductorBaseModel):
    __tablename__ = "conductor_environments"

    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    image_tag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
