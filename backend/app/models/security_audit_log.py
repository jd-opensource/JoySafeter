"""
Security audit log model
"""

import uuid
from typing import Optional

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class SecurityAuditLog(Base, TimestampMixin):
    """
    Security audit log table.

    Record all security-related events for:
    - Security event tracking
    - Anomalous behavior detection
    - Compliance requirements (SOC 2, GDPR, etc.)
    """

    __tablename__ = "security_audit_log"
    __table_args__ = (
        Index("audit_log_user_id_idx", "user_id"),
        Index("audit_log_event_type_idx", "event_type"),
        Index("audit_log_event_status_idx", "event_status"),
        Index("audit_log_created_at_idx", "created_at"),
        Index("audit_log_user_event_idx", "user_id", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # user info (optional; unauthenticated operations may lack user_id)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # event info
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="event type: login, logout, password_change, password_reset, 2fa_enable, account_lock, etc.",
    )
    event_status: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="event status: success, failure, blocked"
    )

    # request info
    ip_address: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # details (JSON)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="extra info such as error reason, target entity, etc.")

    # timestamps (inherited from TimestampMixin)
    # created_at records when the event occurred
