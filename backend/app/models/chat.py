"""
Chat model
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class Chat(BaseModel):
    __tablename__ = "chat"

    agent_graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    customizations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Authentication options
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="public")
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    allowed_emails: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Output configuration
    output_configs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (UniqueConstraint("identifier", name="identifier_idx"),)
