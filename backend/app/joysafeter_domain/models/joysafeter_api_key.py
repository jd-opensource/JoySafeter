"""
JoySafeter API key model — project-scoped API keys for programmatic access.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel


class JoySafeterApiKey(JoySafeterBaseModel):
    """
    API key for authenticating joysafeter API requests.

    Scoped to a project and organization.  Uses UUID v7 PK (JoySafeter pattern).
    """

    __tablename__ = "joysafeter_api_keys"
    __table_args__ = (
        Index("uq_api_keys_key_hash", "key_hash", unique=True),
        Index("idx_cak_project", "project_id"),
        Index("idx_cak_org", "org_id"),
        Index(
            "ix_api_keys_active_project_created_id",
            "project_id",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("revoked_at IS NULL"),
        ),
        CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="api_keys_role"),
        CheckConstraint("length(btrim(name)) > 0", name="api_keys_name"),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at", name="api_keys_expiry"),
        ForeignKeyConstraint(
            ["project_id", "org_id"],
            ["joysafeter_organization_projects.id", "joysafeter_organization_projects.org_id"],
            name="fk_api_keys_project_org",
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project capability in the project vocabulary (admin / editor / viewer;
    # see ProjectRole). Defaults to viewer (least privilege).
    role: Mapped[str] = mapped_column(Text, nullable=False, default="viewer")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
