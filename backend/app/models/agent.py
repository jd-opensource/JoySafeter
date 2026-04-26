from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.datetime import utc_now

from .base import BaseModel

if TYPE_CHECKING:
    pass


class Agent(BaseModel):
    """An agent owned by a workspace."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
        Index("ix_agents_workspace_id", "workspace_id"),
        Index("ix_agents_status", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "archived", name="agent_status"), nullable=False, default="draft"
    )
    current_draft_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True
    )
    active_release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_releases.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    encrypted_custom_env: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def has_custom_env(self) -> bool:
        return self.encrypted_custom_env is not None

    # Relationships
    versions: Mapped[List[AgentVersion]] = relationship(
        "AgentVersion",
        back_populates="agent",
        foreign_keys="AgentVersion.agent_id",
    )
    current_draft_version: Mapped[Optional[AgentVersion]] = relationship(
        "AgentVersion",
        foreign_keys=[current_draft_version_id],
    )
    active_release: Mapped[Optional[AgentRelease]] = relationship(
        "AgentRelease",
        foreign_keys=[active_release_id],
    )


class AgentVersion(Base):
    """An immutable snapshot of an agent's configuration at a point in time."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("draft", "frozen", name="agent_version_status"), nullable=False, default="draft"
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    definition_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    definition_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capability_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    # Relationships
    agent: Mapped[Agent] = relationship(
        "Agent",
        back_populates="versions",
        foreign_keys=[agent_id],
    )


class AgentRelease(Base):
    """A release artifact built from a specific agent version."""

    __tablename__ = "agent_releases"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "release_number", name="uq_agent_releases_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False)
    release_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("ready", "failed", "retired", name="agent_release_status"),
        nullable=False,
        default="ready",
    )
    runtime_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    builder_kind: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    executable_ref: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    runtime_binding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("user.id"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    version: Mapped[AgentVersion] = relationship("AgentVersion")
