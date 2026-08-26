"""Sandbox network policy control-plane state."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterModel
from app.joysafeter_shared.ids import SandboxId, SandboxNetworkPolicyId, SessionId, TaskId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType


class JoySafeterSandboxNetworkPolicy(JoySafeterModel):
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

    id: Mapped[SandboxNetworkPolicyId] = mapped_column(EntityIdType(SandboxNetworkPolicyId), primary_key=True)

    sandbox_id: Mapped[SandboxId] = mapped_column(
        EntityIdType(SandboxId), ForeignKey("joysafeter_sandboxes.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[Optional[SessionId]] = mapped_column(
        EntityIdType(SessionId), ForeignKey("joysafeter_sessions.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[Optional[TaskId]] = mapped_column(
        EntityIdType(TaskId), ForeignKey("joysafeter_tasks.id", ondelete="SET NULL"), nullable=True
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
