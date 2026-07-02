"""
Skill subsystem models.

Consolidated here from the former ``skill_version.py`` /
``skill_collaborator.py`` / ``skill_usage_log.py`` modules — one file for
the whole managed-agent skill subsystem:

  - Skill / SkillFile / SkillSecurityScan        (core skill + content + scans)
  - SkillVersion / SkillVersionFile              (immutable published snapshots)
  - SkillCollaborator (+ CollaboratorRole)       (per-skill RBAC)
  - SkillUsageLog                                (append-only pack/load audit)
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.joysafeter_shared.database import Base

from .base import BaseModel, TimestampMixin

if TYPE_CHECKING:
    from .joysafeter_auth import AuthUser


class JoySafeterSkillVisibility(str, enum.Enum):
    """Where a skill is reachable from.

    The states deliberately escalate: ``private`` is the most restrictive
    and ``public`` is the most permissive. ``check_skill_access`` walks them
    in that order and short-circuits on the first match.
    """

    PRIVATE = "private"
    PROJECT = "project"
    ORGANIZATION = "organization"
    PUBLIC = "public"


class JoySafeterSkillLifecycleStatus(str, enum.Enum):
    """Where a skill is in its review/publish workflow.

    Allowed transitions (enforced by ``SkillLifecycleService``):

      draft           -> pending_review
      pending_review  -> approved | rejected
      rejected        -> draft           (resubmit cycle)
      approved        -> archived
      archived        -> approved        (un-archive)

    Other transitions are rejected with ``InvalidRequestError``. The
    runtime gate (``skill_runtime_policy.is_skill_usable``) only loads
    skills in ``approved``.
    """

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class JoySafeterSkill(BaseModel):
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
    # DEPRECATED — replaced by ``visibility``. Kept for one release cycle
    # so any external code that still reads ``is_public`` keeps working.
    # The service writer dual-writes both fields; readers prefer
    # ``visibility``. Slated for removal in P1+1.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # P1: four-tier sharing surface. ``private`` is the conservative
    # default for new rows; the service derives the right value from the
    # caller's input (project_id + explicit visibility override).
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default=JoySafeterSkillVisibility.PRIVATE.value)
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
    # Lifecycle gate, independent of security verdict. The runtime loader
    # only accepts ``approved``. New skills start in ``draft`` so the owner
    # has a chance to scan and verify before letting agents pick them up.
    # Legacy data is promoted to ``approved`` by
    # 20260625_000004_promote_legacy_skills_approved.
    lifecycle_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=JoySafeterSkillLifecycleStatus.DRAFT.value
    )

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
    files: Mapped[List["JoySafeterSkillFile"]] = relationship(
        "JoySafeterSkillFile",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Non-mapped, request-scoped annotation. The service layer sets this to
    # the latest published version string (or leaves it None) before the row
    # is serialized by ``SkillResponse``. Declaring it as a ClassVar keeps it
    # off the ORM mapper while making ``getattr(skill, "latest_version")``
    # safe even on rows that were never passed through the attach step.
    latest_version: ClassVar[Optional[str]] = None

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
        Index("skills_lifecycle_status_idx", "lifecycle_status"),
        Index("skills_visibility_idx", "visibility"),
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


class JoySafeterSkillFile(BaseModel):
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
    skill: Mapped["JoySafeterSkill"] = relationship("JoySafeterSkill", back_populates="files", lazy="selectin")

    __table_args__ = (
        Index("skill_files_skill_idx", "skill_id"),
        Index("skill_files_path_idx", "skill_id", "path"),
    )


class JoySafeterSkillSecurityScan(BaseModel):
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
    # SkillSpector ruleset version that produced this scan. Nullable: pre-
    # migration scans and scans where the scanner omits the field keep NULL
    # — treated as "unknown ruleset" by the rescan selector.
    ruleset_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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

    # ---------------------------------------------------------------------------
    # Skill versions — immutable published snapshots
    # ---------------------------------------------------------------------------


class JoySafeterSkillVersion(BaseModel):
    """Published immutable version snapshot of a Skill."""

    __tablename__ = "joysafeter_skill_versions"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    release_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot fields
    skill_name: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    meta_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    compatibility: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    published_by_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # P2 — version-level security + lifecycle. ``security_scan_id``
    # binds the version to the exact scan that signed off on its
    # content; ``target_hash`` mirrors that scan's hash so the runtime
    # drift gate can reject a version whose snapshot somehow no longer
    # matches the recorded scan. ``lifecycle_status`` is independent
    # of the parent skill's status — a published version stays approved
    # even after the owner archives the parent skill, until the
    # version itself is explicitly archived.
    security_scan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skill_security_scans.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="approved",  # versions are typically created from an approved skill
    )
    approved_by_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    skill: Mapped["JoySafeterSkill"] = relationship("JoySafeterSkill", lazy="selectin")
    published_by: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[published_by_id], lazy="selectin")
    approved_by: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[approved_by_id], lazy="selectin")
    files: Mapped[List["JoySafeterSkillVersionFile"]] = relationship(
        "JoySafeterSkillVersionFile",
        back_populates="version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="skill_versions_skill_version_unique"),
        Index("skill_versions_skill_idx", "skill_id"),
        Index("skill_versions_published_at_idx", "published_at"),
        Index("skill_versions_lifecycle_status_idx", "lifecycle_status"),
        Index("skill_versions_security_scan_idx", "security_scan_id"),
    )


class JoySafeterSkillVersionFile(BaseModel):
    """File snapshot belonging to a published version."""

    __tablename__ = "joysafeter_skill_version_files"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skill_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="database")
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    version: Mapped["JoySafeterSkillVersion"] = relationship(
        "JoySafeterSkillVersion", back_populates="files", lazy="selectin"
    )

    __table_args__ = (Index("skill_version_files_version_idx", "version_id"),)

    # ---------------------------------------------------------------------------
    # Skill collaborators — per-skill role-based access control
    # ---------------------------------------------------------------------------


class JoySafeterCollaboratorRole(str, enum.Enum):
    """Roles ordered by privilege: viewer < editor < publisher < admin."""

    viewer = "viewer"
    editor = "editor"
    publisher = "publisher"
    admin = "admin"

    @classmethod
    def rank(cls, role: "JoySafeterCollaboratorRole") -> int:
        _order = [cls.viewer, cls.editor, cls.publisher, cls.admin]
        return _order.index(role)

    def __ge__(self, other):
        if not isinstance(other, JoySafeterCollaboratorRole):
            return NotImplemented
        return JoySafeterCollaboratorRole.rank(self) >= JoySafeterCollaboratorRole.rank(other)

    def __gt__(self, other):
        if not isinstance(other, JoySafeterCollaboratorRole):
            return NotImplemented
        return JoySafeterCollaboratorRole.rank(self) > JoySafeterCollaboratorRole.rank(other)

    def __le__(self, other):
        if not isinstance(other, JoySafeterCollaboratorRole):
            return NotImplemented
        return JoySafeterCollaboratorRole.rank(self) <= JoySafeterCollaboratorRole.rank(other)

    def __lt__(self, other):
        if not isinstance(other, JoySafeterCollaboratorRole):
            return NotImplemented
        return JoySafeterCollaboratorRole.rank(self) < JoySafeterCollaboratorRole.rank(other)


class JoySafeterSkillCollaborator(BaseModel):
    """Per-skill collaborator with role."""

    __tablename__ = "joysafeter_skill_collaborators"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[JoySafeterCollaboratorRole] = mapped_column(
        Enum(JoySafeterCollaboratorRole, name="collaborator_role", create_constraint=True),
        nullable=False,
    )
    invited_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    skill: Mapped["JoySafeterSkill"] = relationship("JoySafeterSkill", lazy="selectin")
    user: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="skill_collaborators_skill_user_unique"),
        Index("skill_collaborators_user_skill_idx", "user_id", "skill_id"),
    )

    # ---------------------------------------------------------------------------
    # Skill usage log — append-only pack/load audit trail
    #
    # Append-only event log: one row per time a SkillPacker successfully packs
    # a skill into a sandbox bundle. Deliberately decoupled from
    # ``joysafeter_skill_security_scans`` — scans record what was *checked*,
    # usage logs record what was *executed*. Both matter independently.
    # ---------------------------------------------------------------------------


class JoySafeterSkillUsageLog(Base, TimestampMixin):
    """One row per successful skill pack into a session bundle.

    ``created_at`` (from ``TimestampMixin``) is the load timestamp; no
    ``updated_at`` semantics — rows are insert-only by design.
    """

    __tablename__ = "joysafeter_skill_usage_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # The skill that was loaded. ON DELETE SET NULL so the audit trail
    # survives a skill deletion; the FK constraint stays for queryability.
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_skills.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Resolved version label, if any. Free-form to admit both semver
    # strings ("1.2.3"), the ``"latest"`` keyword (which the packer
    # rewrites to a concrete version before logging), and ``"draft"``.
    # Nullable for legacy ``tar_gz_b64`` direct-packed sessions where
    # there is no DB-side skill version.
    skill_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Which session loaded this skill. String not UUID because session
    # ids in v2 are JoySafeter-managed strings.
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # The agent that owned the session at load time. Captured separately
    # from session so we can answer "which agents historically used skill
    # X" without joining through sessions.
    agent_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Project the session belonged to — useful for org-level audit
    # queries ("everything our project loaded yesterday").
    project_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # The user whose actions triggered the load. Distinct from the
    # skill's owner — a viewer with project access can trigger a load.
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # Hot query: "what did session X load?" — covers the
        # debug-a-failed-session flow.
        Index(
            "skill_usage_log_session_created_idx",
            "session_id",
            "created_at",
        ),
        # Hot query: "who's been using skill X?" — covers the security
        # response flow.
        Index(
            "skill_usage_log_skill_created_idx",
            "skill_id",
            "created_at",
        ),
        # Less hot: project-level audit roll-ups.
        Index(
            "skill_usage_log_project_created_idx",
            "project_id",
            "created_at",
        ),
    )
