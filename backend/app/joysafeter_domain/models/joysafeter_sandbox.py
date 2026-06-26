"""
Sandbox Model (v2 JoySafeterSandbox).

NOTE: the legacy ``UserSandbox`` model (table ``user_sandbox``) was removed in
the v1 cleanup — managed sandboxes run entirely on ``JoySafeterSandbox`` below.
The ``user_sandbox`` table was dropped in alembic 20260626_000002; this module
was renamed from ``sandbox.py`` to ``joysafeter_sandbox.py`` to match the table.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterBaseModel


class JoySafeterSandbox(JoySafeterBaseModel):
    __tablename__ = "joysafeter_sandboxes"
    __table_args__ = (
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
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("joysafeter_organization_projects.id"), nullable=True, index=True,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="docker")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="creating")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    chat_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    image: Mapped[str] = mapped_column(Text, nullable=False)
    last_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set when the runner reports RunnerIdle (sandbox is precisely "all done",
    # including any background sub-agents — cc holds back result until they
    # finish; codex aggregates child threads in the runtime adapter). Cleared
    # when the sandbox transitions back to running. The idle sweeper uses this
    # as the authoritative idle criterion instead of last_used_at, which used
    # to be touched on every heartbeat and bloated the row.
    idle_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the gRPC bridge for this sandbox disconnects (EOF / heartbeat
    # timeout / cancel). Cleared on the next successful runner connection.
    # The sweeper reaps sandboxes whose bridge has been gone past the grace
    # window — primary fallback against runner crashes that prevented an
    # ordinary RunnerIdle from ever firing.
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    destroyed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    workspace_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
