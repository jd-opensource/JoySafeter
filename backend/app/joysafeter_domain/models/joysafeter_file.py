"""JoySafeterFile model - stores file metadata for uploaded and agent-generated files."""

import uuid
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel, SoftDeleteMixin


class JoySafeterFile(JoySafeterBaseModel, SoftDeleteMixin):
    __tablename__ = "joysafeter_files"

    project_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("joysafeter_organization_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, default="user_upload")
    content_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    downloadable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_joysafeter_files_project_created", "project_id", "created_at"),
        Index("idx_joysafeter_files_session", "session_id"),
        Index("idx_joysafeter_files_deleted", "deleted_at"),
    )
