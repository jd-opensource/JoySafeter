from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.utils.datetime import utc_now

from .base import BaseModel

if TYPE_CHECKING:
    from .agent import Agent


class Thread(BaseModel):
    """A conversation thread between a user and an agent.

    Thread is the session root: it owns the container, the CLI session id,
    and the session_id under which all Traces for its AgentRuns are grouped.
    """

    __tablename__ = "threads"

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id"), nullable=False)

    # Engine identity — populated lazily by the container pool
    container_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cli_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    agent: Mapped[Agent] = relationship("Agent")

    __table_args__ = (
        Index(
            "idx_threads_lru",
            "last_active_at",
            postgresql_where="status = 'active'",
            postgresql_ops={"last_active_at": "DESC"},
        ),
    )

