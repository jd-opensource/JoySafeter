from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base
from app.joysafeter_shared.utils.datetime import utc_now


class JoySafeterCredentialEncryptionCanary(Base):
    __tablename__ = "joysafeter_credential_encryption_canaries"
    __table_args__ = (
        CheckConstraint(
            "key_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'",
            name="key_id_format",
        ),
        CheckConstraint(
            "left(encrypted_canary, length('enc:v2:' || key_id || ':')) = "
            "'enc:v2:' || key_id || ':' AND "
            "length(encrypted_canary) > length('enc:v2:' || key_id || ':')",
            name="envelope_matches_key_id",
        ),
    )

    key_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    encrypted_canary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )
