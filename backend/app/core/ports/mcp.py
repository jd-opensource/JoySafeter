"""MCP server port — type-safe interface for MCP server resolution in core/."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class McpServerPort(Protocol):
    """Port for resolving MCP server instances by name.

    Implemented by: services/mcp_server_service.py (McpServerService)
    Used by: core/tools/mcp_tool_utils.py
    """

    async def get_server_by_name(self, user_id: str, server_name: str) -> Any: ...
