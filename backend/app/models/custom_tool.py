"""
自定义工具模型
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class CustomTool(BaseModel):
    __tablename__ = "custom_tools"

    owner_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    owner: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="custom_tools_owner_name_unique"),
        Index("custom_tools_owner_idx", "owner_id"),
    )
