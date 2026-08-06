"""Sandbox network policy control-plane state."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel
from app.joysafeter_shared.ids import EntityIdType, SessionId


class JoySafeterSandboxNetworkPolicy(JoySafeterBaseModel):
    __tablename__ = "joysafeter_sandbox_network_policies"
    __table_args__ = (
        UniqueConstraint("sandbox_id", "policy_version", name="uq_jsnp_sandbox_policy_version"),
        Index("idx_jsnp_sandbox_status", "sandbox_id", "status"),
        Index("idx_jsnp_policy_hash", "policy_hash"),
        Index("idx_jsnp_status_updated_at", "status", "updated_at"),
        Index("idx_jsnp_created_at", "created_at"),
        Index("idx_jsnp_pushed_at", "pushed_at"),
        Index("idx_jsnp_acked_at", "acked_at"),
    )

    sandbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_sandboxes.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[Optional[SessionId]] = mapped_column(
        EntityIdType(SessionId), ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("joysafeter_tasks.id", ondelete="SET NULL"), nullable=True
    )
    policy_hash: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    desired_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    rendered_summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_nack_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
