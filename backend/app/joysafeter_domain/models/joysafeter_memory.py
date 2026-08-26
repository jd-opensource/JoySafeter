from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterModel
from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import (
    ApiKeyId,
    MemoryId,
    MemoryStoreId,
    MemoryVersionId,
    ProjectId,
    SessionId,
    SessionResourceId,
)
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType


class JoySafeterMemoryStore(JoySafeterModel):
    __tablename__ = "joysafeter_memory_stores"

    id: Mapped[MemoryStoreId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(MemoryStoreId), primary_key=True
    )

    project_id: Mapped[Optional[ProjectId]] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterMemory(JoySafeterModel):
    __tablename__ = "joysafeter_memories"
    __table_args__ = (UniqueConstraint("store_id", "path"),)

    id: Mapped[MemoryId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(MemoryId), primary_key=True
    )
    store_id: Mapped[MemoryStoreId] = mapped_column(
        EntityIdType(MemoryStoreId),
        ForeignKey("joysafeter_memory_stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version_id: Mapped[Optional[MemoryVersionId]] = mapped_column(EntityIdType(MemoryVersionId), nullable=True)


class JoySafeterMemoryVersion(Base):
    __tablename__ = "joysafeter_memory_versions"
    __table_args__ = (
        Index("idx_joysafeter_memory_versions_store_created", "store_id", "created_at"),
        Index("idx_joysafeter_memory_versions_session_created", "session_id", "created_at"),
    )

    id: Mapped[MemoryVersionId] = mapped_column(EntityIdType(MemoryVersionId), primary_key=True)
    store_id: Mapped[MemoryStoreId] = mapped_column(
        EntityIdType(MemoryStoreId),
        ForeignKey("joysafeter_memory_stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_id: Mapped[MemoryId] = mapped_column(EntityIdType(MemoryId), nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_id: Mapped[Optional[SessionId]] = mapped_column(EntityIdType(SessionId), nullable=True)
    api_key_id: Mapped[Optional[ApiKeyId]] = mapped_column(EntityIdType(ApiKeyId), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    redacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    redacted_by: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class JoySafeterSessionMemoryStore(Base):
    __tablename__ = "joysafeter_session_memory_stores"
    __table_args__ = (
        UniqueConstraint("session_id", "store_id"),
        Index("idx_joysafeter_session_memory_stores_created", "created_at"),
    )

    id: Mapped[SessionResourceId] = mapped_column(EntityIdType(SessionResourceId), primary_key=True)
    session_id: Mapped[SessionId] = mapped_column(
        EntityIdType(SessionId),
        ForeignKey("joysafeter_sessions.id"),
        nullable=False,
    )
    store_id: Mapped[MemoryStoreId] = mapped_column(
        EntityIdType(MemoryStoreId),
        ForeignKey("joysafeter_memory_stores.id"),
        nullable=False,
    )
    access: Mapped[str] = mapped_column(Text, nullable=False, default="read_write")
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mount_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
