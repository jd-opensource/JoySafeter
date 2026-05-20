import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Text, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ConductorSandbox(BaseModel):
    __tablename__ = "conductor_sandboxes"
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
    destroyed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    workspace_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
