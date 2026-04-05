"""
GraphExecution model -- track Graph executions triggered via OpenAPI.
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


def utc_now():
    return datetime.now(timezone.utc)


class ExecutionStatus(str, enum.Enum):
    INIT = "init"
    EXECUTING = "executing"
    FINISH = "finish"
    FAILED = "failed"


class GraphExecution(BaseModel):
    """OpenAPI Graph execution record."""

    __tablename__ = "graph_executions"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, values_callable=lambda e: [m.value for m in e]),
        default=ExecutionStatus.INIT,
        nullable=False,
    )
    input_variables: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("graph_executions_graph_id_idx", "graph_id"),
        Index("graph_executions_user_id_idx", "user_id"),
        Index("graph_executions_status_idx", "status"),
    )
