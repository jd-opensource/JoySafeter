"""MCP server port — type-safe interface for MCP server resolution in core/."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.models.mcp import McpServer


@runtime_checkable
class McpServerPort(Protocol):
    """Port for resolving MCP server instances by name.

    Implemented by: services/mcp_server_service.py (McpServerService)
    Used by: core/tools/mcp_tool_utils.py
    """

    async def get_server_by_name(self, user_id: str, server_name: str) -> McpServer | None: ...
