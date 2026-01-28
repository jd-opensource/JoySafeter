"""
MCP Server 配置模型

用户级别的 MCP 服务器管理：
- user_id 必填：MCP 服务器的所有者
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from .auth import AuthUser


class McpServer(BaseModel, SoftDeleteMixin):
    __tablename__ = "mcp_servers"

    # Owner (required) - user who owns this MCP server
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Audit field - who created this record (may differ from owner in some cases)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Server identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Connection configuration
    transport: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    timeout: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=30000)
    retries: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=3)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_connected: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    connection_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="disconnected")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Tool statistics
    tool_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    last_tools_refresh: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Usage statistics
    total_requests: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    last_used: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    owner: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    creator: Mapped[Optional["AuthUser"]] = relationship("AuthUser", foreign_keys=[created_by], lazy="selectin")

    __table_args__ = (
        # User queries
        Index("mcp_servers_user_id_idx", "user_id"),
        Index("mcp_servers_user_enabled_idx", "user_id", "enabled"),
        # Unique constraint: server name must be unique per user
        Index("mcp_servers_user_name_unique_idx", "user_id", "name", unique=True),
    )
