"""JoySafeter sandbox model."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterModel
from app.joysafeter_shared.ids import ProjectId, SandboxId, SessionId, TaskId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType


class JoySafeterSandbox(JoySafeterModel):
    __tablename__ = "joysafeter_sandboxes"
    __table_args__ = (
        CheckConstraint(
            "networking_status IN ('disabled', 'pending', 'ready', 'nacked', 'failed')",
            name="ck_sandbox_networking_status",
        ),
        CheckConstraint(
            "(networking_policy_hash IS NULL AND networking_policy_version = 0) OR "
            "(networking_policy_hash IS NOT NULL AND length(btrim(networking_policy_hash)) > 0 "
            "AND networking_policy_version > 0)",
            name="ck_sandbox_desired_network_policy_generation",
        ),
        CheckConstraint(
            "(networking_applied_hash IS NULL AND networking_applied_version IS NULL) OR "
            "(networking_applied_hash IS NOT NULL AND length(btrim(networking_applied_hash)) > 0 "
            "AND networking_applied_version > 0)",
            name="ck_sandbox_applied_network_policy_generation",
        ),
        CheckConstraint(
            "networking_status <> 'ready' OR "
            "(networking_policy_hash IS NOT NULL AND networking_applied_hash IS NOT NULL "
            "AND networking_policy_version > 0 AND networking_applied_version > 0 "
            "AND networking_policy_hash = networking_applied_hash "
            "AND networking_policy_version = networking_applied_version)",
            name="ck_sandbox_ready_network_policy_generation",
        ),
        CheckConstraint(
            "runtime_config_status IN ('ready', 'restart_required')",
            name="ck_joysafeter_sandboxes_runtime_config_status",
        ),
        Index("idx_csb_status", "status"),
        Index(
            "idx_csb_pool",
            "created_at",
            postgresql_where="status = 'pooled'",
        ),
        Index(
            "idx_csb_session",
            "chat_session_id",
            postgresql_where="chat_session_id IS NOT NULL",
        ),
        Index(
            "idx_csb_active_session_unique",
            "chat_session_id",
            unique=True,
            postgresql_where=(
                "chat_session_id IS NOT NULL AND destroyed_at IS NULL AND "
                "status IN ('creating', 'provisioning', 'idle', 'running', "
                "'stopped', 'error')"
            ),
        ),
        Index("idx_csb_project", "project_id"),
        Index("idx_csb_last_used", "last_used_at"),
        Index("idx_csb_updated", "updated_at"),
        Index("idx_csb_destroyed", "destroyed_at"),
    )

    id: Mapped[SandboxId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(SandboxId), primary_key=True
    )
    project_id: Mapped[Optional[ProjectId]] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="docker")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="creating")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    chat_session_id: Mapped[Optional[SessionId]] = mapped_column(EntityIdType(SessionId), nullable=True)
    image: Mapped[str] = mapped_column(Text, nullable=False)
    last_task_id: Mapped[Optional[TaskId]] = mapped_column(EntityIdType(TaskId), nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Set when the runner reports RunnerIdle (sandbox is precisely "all done",
    # including any background sub-agents — cc holds back result until they
    # finish; codex aggregates child threads in the runtime adapter). Cleared
    # when the sandbox transitions back to running. The idle sweeper uses this
    # as the authoritative idle criterion instead of last_used_at, which used
    # to be touched on every heartbeat and bloated the row.
    idle_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the gRPC bridge for this sandbox disconnects (EOF / heartbeat
    # timeout / cancel). Cleared on the next successful runner connection.
    # The sweeper reaps sandboxes whose bridge has been gone past the grace
    # window — primary fallback against runner crashes that prevented an
    # ordinary RunnerIdle from ever firing.
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    destroyed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    networking_status: Mapped[str] = mapped_column(Text, nullable=False, default="disabled", server_default="disabled")
    networking_policy_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    networking_policy_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    networking_applied_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    networking_applied_version: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    networking_last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    networking_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_config_status: Mapped[str] = mapped_column(Text, nullable=False, default="ready", server_default="ready")
    runtime_config_last_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_config_required_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_config_applied_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
