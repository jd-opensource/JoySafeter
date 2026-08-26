"""JoySafeterSessionRepo model - links git repositories to sessions for cloning.

Mirrors the official Managed Agents ``github_repository`` session resource. The
clone credential is stored encrypted (``encrypted_token``) and is never returned
in API responses.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.ids import SessionId, SessionResourceId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType
from app.joysafeter_shared.utils.datetime import utc_now


class JoySafeterSessionRepo(Base):
    __tablename__ = "joysafeter_session_repos"

    id: Mapped[SessionResourceId] = mapped_column(EntityIdType(SessionResourceId), primary_key=True)
    session_id: Mapped[SessionId] = mapped_column(
        EntityIdType(SessionId),
        ForeignKey("joysafeter_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mount_path: Mapped[str] = mapped_column(Text, nullable=False)
    mount_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Clone-only credential, encrypted at rest via CredentialCipher. Never echoed.
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    @property
    def has_authorization_token(self) -> bool:
        return bool(self.encrypted_token) and self.token_erased_at is None

    @property
    def token_status(self) -> str:
        if self.token_erased_at is not None:
            return "erased"
        if not self.encrypted_token:
            return "none"
        if self.token_expires_at is not None and self.token_expires_at <= utc_now():
            return "expired"
        return "active"

    __table_args__ = (
        CheckConstraint(
            "token_erased_at IS NULL OR encrypted_token = ''",
            name="session_repo_token_erasure_consistent",
        ),
        CheckConstraint(
            "encrypted_token = '' OR token_rotated_at IS NOT NULL",
            name="session_repo_token_rotation_present",
        ),
        Index("idx_session_repos_session", "session_id"),
        Index(
            "ix_session_repo_token_pending_expiry",
            "token_expires_at",
            "id",
            postgresql_where=(encrypted_token != "") & token_expires_at.is_not(None),
        ),
    )
