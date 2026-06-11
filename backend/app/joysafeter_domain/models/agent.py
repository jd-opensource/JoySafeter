from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_utils import uuid7

from app.joysafeter_domain.contracts.agent import normalize_engine_kind, normalize_runtime_kind
from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now

from .base import BaseModel, JoySafeterBaseModel, TimestampMixin

if TYPE_CHECKING:
    pass


class Agent(BaseModel):
    """An agent owned by a project."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_agents_project_slug"),
        Index("ix_agents_project_id", "project_id"),
        Index("ix_agents_status", "status"),
    )

    project_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "archived", name="agent_status"), nullable=False, default="draft"
    )
    current_draft_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", use_alter=True), nullable=True
    )
    active_release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_releases.id", use_alter=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    encrypted_custom_env: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def has_custom_env(self) -> bool:
        return self.encrypted_custom_env is not None

    @property
    def engine_kind(self) -> Optional[str]:
        if not self.current_draft_version:
            return None
        return normalize_engine_kind(self.current_draft_version.engine_kind)

    @property
    def runtime_kind(self) -> Optional[str]:
        if not self.active_release:
            return None
        return normalize_runtime_kind(self.active_release.runtime_kind)

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
    __table_args__ = (UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("draft", "frozen", name="agent_version_status"), nullable=False, default="draft"
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    engine_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    definition_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capability_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
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
    __table_args__ = (UniqueConstraint("agent_version_id", "release_number", name="uq_agent_releases_version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False
    )
    release_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("ready", "active", "superseded", "failed", "retired", name="agent_release_status"),
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


# ---------------------------------------------------------------------------
# JoySafeter Agent models
# ---------------------------------------------------------------------------


class JoySafeterAgent(JoySafeterBaseModel):
    __tablename__ = "joysafeter_agents"
    __table_args__ = (
        UniqueConstraint("name", name="idx_ca_name_unique"),
        Index("idx_ca_created_at", "created_at"),
        Index("idx_ca_project", "project_id"),
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    engine_kind: Mapped[str] = mapped_column(Text, nullable=False, default="claude")
    model: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    env: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    mcp_configs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    agents: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    commands: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    permission_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="bypassPermissions"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    multiagent: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    environment_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secret_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    versions: Mapped[list["JoySafeterAgentVersion"]] = relationship(
        back_populates="agent", lazy="selectin"
    )


class JoySafeterAgentVersion(Base, TimestampMixin):
    __tablename__ = "joysafeter_agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=lambda ctx=None: uuid7()
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    agent: Mapped["JoySafeterAgent"] = relationship(back_populates="versions")
