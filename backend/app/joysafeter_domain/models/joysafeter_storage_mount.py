from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel


class JoySafeterStorageVolume(JoySafeterBaseModel):
    __tablename__ = "joysafeter_storage_volumes"
    __table_args__ = (
        Index(
            "uq_joysafeter_storage_volumes_ref_active",
            "volume_ref",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("idx_joysafeter_storage_volumes_enabled", "enabled"),
    )

    volume_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_type: Mapped[str] = mapped_column(String(32), nullable=False, default="generic", server_default="generic")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    max_access: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only", server_default="read_only")
    allowed_prefixes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    docker: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    k8s: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    quota_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterStorageProjectGrant(JoySafeterBaseModel):
    __tablename__ = "joysafeter_storage_project_grants"
    __table_args__ = (
        UniqueConstraint("volume_id", "project_id", name="uq_joysafeter_storage_grants_volume_project"),
        Index("idx_joysafeter_storage_grants_project", "project_id"),
        Index("idx_joysafeter_storage_grants_volume", "volume_id"),
    )

    volume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_storage_volumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    max_access: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only", server_default="read_only")
    allowed_prefixes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    quota_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class JoySafeterStorageOrganizationGrant(JoySafeterBaseModel):
    __tablename__ = "joysafeter_storage_organization_grants"
    __table_args__ = (
        UniqueConstraint("volume_id", "org_id", name="uq_joysafeter_storage_org_grants_volume_org"),
        Index("idx_joysafeter_storage_org_grants_org", "org_id"),
        Index("idx_joysafeter_storage_org_grants_volume", "volume_id"),
    )

    volume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_storage_volumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    max_access: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only", server_default="read_only")
    allowed_prefixes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    quota_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class JoySafeterSessionStorageMount(JoySafeterBaseModel):
    __tablename__ = "joysafeter_session_storage_mounts"
    __table_args__ = (
        Index("idx_joysafeter_session_storage_mounts_session", "session_id"),
        Index("idx_joysafeter_session_storage_mounts_volume", "volume_id"),
        Index("idx_joysafeter_session_storage_mounts_project", "project_id"),
        UniqueConstraint("session_id", "mount_path", name="uq_joysafeter_session_storage_mount_path"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_storage_volumes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sub_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    mount_path: Mapped[str] = mapped_column(Text, nullable=False)
    access: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only", server_default="read_only")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    detached_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JoySafeterStorageMountAudit(JoySafeterBaseModel):
    __tablename__ = "joysafeter_storage_mount_audit"
    __table_args__ = (
        Index("idx_joysafeter_storage_audit_project_created", "project_id", "created_at"),
        Index("idx_joysafeter_storage_audit_session", "session_id"),
        Index("idx_joysafeter_storage_audit_volume", "volume_id"),
        Index("idx_joysafeter_storage_audit_action", "action"),
    )

    volume_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_storage_volumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    environment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    volume_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mount_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sub_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    access: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    bytes_used: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="success", server_default="success")
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
