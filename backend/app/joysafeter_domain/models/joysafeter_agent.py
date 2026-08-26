from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import AgentId, AgentVersionId, CredentialId, EnvironmentId, ProjectId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

from .base import JoySafeterModel, TimestampMixin


class JoySafeterAgent(JoySafeterModel):
    __tablename__ = "joysafeter_agents"
    __table_args__ = (
        Index(
            "uq_joysafeter_agents_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_joysafeter_agents_global_name",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NULL AND deleted_at IS NULL"),
        ),
        Index("idx_ca_created_at", "created_at"),
        Index("idx_ca_project", "project_id"),
    )

    id: Mapped[AgentId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(AgentId), primary_key=True
    )

    project_id: Mapped[Optional[ProjectId]] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    engine_kind: Mapped[str] = mapped_column(Text, nullable=False, default="claude")
    model: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    env: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    mcp_servers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    agents: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    commands: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    permission_mode: Mapped[str] = mapped_column(Text, nullable=False, default="bypassPermissions")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    multiagent: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    environment_id: Mapped[Optional[EnvironmentId]] = mapped_column(
        EntityIdType(EnvironmentId),
        ForeignKey("joysafeter_environments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    model_credential_id: Mapped[Optional[CredentialId]] = mapped_column(
        EntityIdType(CredentialId),
        ForeignKey("joysafeter_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list["JoySafeterAgentVersion"]] = relationship(back_populates="agent", lazy="selectin")


class JoySafeterAgentVersion(Base, TimestampMixin):
    __tablename__ = "joysafeter_agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: Mapped[AgentVersionId] = mapped_column(EntityIdType(AgentVersionId), primary_key=True)
    agent_id: Mapped[AgentId] = mapped_column(
        EntityIdType(AgentId),
        ForeignKey("joysafeter_agents.id"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    agent: Mapped["JoySafeterAgent"] = relationship(back_populates="versions")
