import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.core.database import Base
from app.models.base import TimestampMixin


class ConductorMemoryStore(BaseModel):
    __tablename__ = "conductor_memory_stores"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ConductorMemory(BaseModel):
    __tablename__ = "conductor_memories"
    __table_args__ = (UniqueConstraint("store_id", "path"),)

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_memory_stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class ConductorMemoryVersion(Base):
    __tablename__ = "conductor_memory_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_memory_stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    api_key_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    redacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redacted_by: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class ConductorSessionMemoryStore(Base):
    __tablename__ = "conductor_session_memory_stores"
    __table_args__ = (UniqueConstraint("session_id", "store_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_sessions.id"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conductor_memory_stores.id"),
        nullable=False,
    )
    access: Mapped[str] = mapped_column(Text, nullable=False, default="read_write")
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mount_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
