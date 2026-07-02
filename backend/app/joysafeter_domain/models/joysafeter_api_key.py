"""
JoySafeter API key model — project-scoped API keys for programmatic access.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel


class JoySafeterApiKey(JoySafeterBaseModel):
    """
    API key for authenticating joysafeter API requests.

    Scoped to a project and organization.  Uses UUID v7 PK (JoySafeter pattern).
    """

    __tablename__ = "joysafeter_api_keys"
    __table_args__ = (
        Index("idx_cak_key_hash", "key_hash"),
        Index("idx_cak_project", "project_id"),
        Index("idx_cak_org", "org_id"),
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
    role: Mapped[str] = mapped_column(Text, nullable=False, default="developer")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
