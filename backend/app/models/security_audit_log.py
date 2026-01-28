"""
安全审计日志模型
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
    安全审计日志表

    记录所有安全相关事件，用于：
    - 安全事件追踪
    - 异常行为检测
    - 合规要求（SOC 2, GDPR等）
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

    # 用户信息（可选，未登录操作可能没有 user_id）
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 事件信息
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="事件类型：login, logout, password_change, password_reset, 2fa_enable, account_lock, etc.",
    )
    event_status: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="事件状态：success, failure, blocked"
    )

    # 请求信息
    ip_address: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # 详细信息（JSON）
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="额外信息，如错误原因、操作对象等")

    # 时间戳（继承自 TimestampMixin）
    # created_at 用于记录事件发生时间
