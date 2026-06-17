"""
Skill model
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class Skill(BaseModel):
    """Skill table."""

    __tablename__ = "joysafeter_skills"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    root_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id", ondelete="SET NULL"), nullable=True
    )
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    compatibility: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    meta_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    security_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_scanned")
    security_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    security_severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    security_recommendation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    security_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    security_scan_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    security_scan_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    security_issues_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    security_critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    security_high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    security_medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    security_low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # relationships
    owner: Mapped[Optional["AuthUser"]] = relationship(
        "AuthUser",
        foreign_keys=[owner_id],
        lazy="selectin",
    )
    created_by: Mapped["AuthUser"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    files: Mapped[List["SkillFile"]] = relationship(
        "SkillFile",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="skills_owner_name_unique"),
        Index("skills_owner_idx", "owner_id"),
        Index("skills_created_by_idx", "created_by_id"),
        Index("skills_public_idx", "is_public"),
        Index("skills_project_idx", "project_id"),
        Index("skills_tags_idx", "tags", postgresql_using="gin"),
        Index("skills_security_status_idx", "security_status"),
        Index("skills_security_severity_idx", "security_severity"),
        Index("skills_security_recommendation_idx", "security_recommendation"),
    )

    @property
    def security_scan(self) -> dict:
        """Latest security scan summary for API responses."""
        return {
            "status": self.security_status,
            "score": self.security_score,
            "severity": self.security_severity,
            "recommendation": self.security_recommendation,
            "issues_count": self.security_issues_count,
            "critical_count": self.security_critical_count,
            "high_count": self.security_high_count,
            "medium_count": self.security_medium_count,
            "low_count": self.security_low_count,
            "scanned_at": self.security_scanned_at,
            "scan_id": self.security_scan_id,
            "target_hash": self.security_scan_hash,
        }


class SkillFile(BaseModel):
    """Skill file table."""

    __tablename__ = "joysafeter_skill_files"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="database")
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # relationship
    skill: Mapped["Skill"] = relationship("Skill", back_populates="files", lazy="selectin")

    __table_args__ = (
        Index("skill_files_skill_idx", "skill_id"),
        Index("skill_files_path_idx", "skill_id", "path"),
    )


class SkillSecurityScan(BaseModel):
    """Security scan history for Skill content."""

    __tablename__ = "joysafeter_skill_security_scans"

    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skills.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    target_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scanner: Mapped[str] = mapped_column(String(64), nullable=False, default="skillspector")
    scanner_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    issues_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("skill_security_scans_skill_created_idx", "skill_id", "created_at"),
        Index("skill_security_scans_project_created_idx", "project_id", "created_at"),
        Index("skill_security_scans_owner_created_idx", "owner_id", "created_at"),
        Index("skill_security_scans_status_created_idx", "status", "created_at"),
        Index("skill_security_scans_severity_created_idx", "severity", "created_at"),
        Index("skill_security_scans_recommendation_created_idx", "recommendation", "created_at"),
        Index("skill_security_scans_target_hash_idx", "target_hash"),
    )
