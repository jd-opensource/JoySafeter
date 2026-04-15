from __future__ import annotations

import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    ERROR = "error"
    OFFLINE = "offline"


class AgentProfile(BaseModel):
    __tablename__ = "agent_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    runtime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, values_callable=lambda e: [m.value for m in e], name="agentstatus"),
        nullable=False,
        default=AgentStatus.OFFLINE,
    )
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    skill_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_env: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    runtime_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(String(50), nullable=False, default="workspace")

    __table_args__ = (
        Index("agent_profiles_workspace_idx", "workspace_id"),
        Index("agent_profiles_workspace_status_idx", "workspace_id", "status"),
    )
