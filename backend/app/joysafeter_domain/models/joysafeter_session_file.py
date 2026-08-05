"""JoySafeterSessionFile model - links files to sessions for mounting."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now


class JoySafeterSessionFile(Base):
    __tablename__ = "joysafeter_session_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    mount_path: Mapped[str] = mapped_column(Text, nullable=False)
    access: Mapped[str] = mapped_column(String(20), nullable=False, default="read_only")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_session_files_session", "session_id"),
        Index("idx_session_files_file", "file_id"),
        Index("idx_session_files_created", "created_at"),
    )
