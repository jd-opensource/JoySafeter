"""JoySafeterSessionRepo model - links git repositories to sessions for cloning.

Mirrors the official Managed Agents ``github_repository`` session resource. The
clone credential is stored encrypted (``encrypted_token``) and is never returned
in API responses.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now


class JoySafeterSessionRepo(Base):
    __tablename__ = "joysafeter_session_repos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("joysafeter_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mount_path: Mapped[str] = mapped_column(Text, nullable=False)
    mount_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Clone-only credential, encrypted at rest via CredentialCipher. Never echoed.
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (Index("idx_session_repos_session", "session_id"),)
