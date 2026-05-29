"""Conductor-specific base model using UUID v7 (matching Rust's Uuid::now_v7)."""
import uuid

from uuid_utils import uuid7

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel as _AppBaseModel


class ConductorBaseModel(_AppBaseModel):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=lambda ctx=None: uuid7(),
    )
