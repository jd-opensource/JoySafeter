"""
API Key 模型
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .workspace import Workspace


class ApiKey(BaseModel):
    __tablename__ = "api_key"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="personal")  # personal/workspace

    last_used: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    creator: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[created_by], lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "(type = 'workspace' AND workspace_id IS NOT NULL) OR (type = 'personal' AND workspace_id IS NULL)",
            name="workspace_type_check",
        ),
        Index("api_key_user_id_idx", "user_id"),
        Index("api_key_workspace_id_idx", "workspace_id"),
        Index("api_key_key_idx", "key"),
    )
