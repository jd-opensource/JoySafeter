"""
MCP Client Service

Encapsulate low-level operations for connecting to MCP servers and fetching tools.
Single responsibility: only handle MCP protocol-level interactions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

from loguru import logger

from app.core.tools.tool import EnhancedTool
from app.models.mcp import McpServer


@dataclass
class McpConnectionConfig:
    """MCP connection configuration."""

    url: str
    transport: str = "streamable-http"
    timeout_seconds: int = 30
    headers: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}


@dataclass
class McpConnectionResult:
    """MCP connection result."""

    success: bool
    tools: List[EnhancedTool]
    error: Optional[str] = None
    latency_ms: Optional[float] = None


@runtime_checkable
class IMcpClient(Protocol):
    """MCP client interface — for dependency injection and testing."""

    async def connect_and_fetch_tools(
        self,
        config: McpConnectionConfig,
    ) -> McpConnectionResult:
        """Connect to an MCP server and fetch the tool list."""
        ...

    async def test_connection(
        self,
        config: McpConnectionConfig,
    ) -> McpConnectionResult:
        """Test the connection."""
        ...


class McpClientService:
    """
    MCP client service.

    Encapsulate low-level interactions with MCP servers:
    - Connection management
    - Tool fetching
    - Connection testing

    Design principles:
    - Single responsibility: only handle MCP protocol interactions
    - Testable: supports mocking via the IMcpClient protocol
    - Extensible: supports different transport types
    """

    async def connect_and_fetch_tools(
        self,
        config: McpConnectionConfig,
        server: McpServer,
    ) -> McpConnectionResult:
        """
        Connect to an MCP server and fetch the tool list.

        Args:
            config: connection configuration
            server: MCP server object

        Returns:
            McpConnectionResult containing the tool list or error info
        """
        start_time = time.time()

        try:
            tools = await self._fetch_tools(config, server)
            latency_ms = (time.time() - start_time) * 1000

            return McpConnectionResult(
                success=True,
                tools=tools,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"Failed to connect to MCP server {config.url}: {e}")

            return McpConnectionResult(
                success=False,
                tools=[],
                error=str(e),
                latency_ms=latency_ms,
            )

    async def test_connection(
        self,
        config: McpConnectionConfig,
        server: Optional[McpServer] = None,
    ) -> McpConnectionResult:
        """
        Test the MCP server connection.

        Args:
            config: connection configuration
            server: MCP server object (optional, for testing before creation)

        Returns:
            McpConnectionResult
        """
        # For test connection before creation, create a minimal server object
        if server is None:
            from app.models.mcp import McpServer

            server = McpServer(
                name="test-connection",
                user_id="test-user",
                url=config.url,
                transport=config.transport,
                timeout=config.timeout_seconds * 1000,
                headers=config.headers or {},
                enabled=True,
            )

        return await self.connect_and_fetch_tools(config, server)

    async def _fetch_tools(
        self,
        config: McpConnectionConfig,
        server: McpServer,
    ) -> List[EnhancedTool]:
        """
        Fetch tool definitions from an MCP server and create an EnhancedTool list.

        Args:
            config: connection configuration (primarily timeout_seconds)
            server: MCP server object

        Returns:
            Tool list (using lazy entrypoints)
        """
        from app.services.mcp_toolkit_manager import get_toolkit_manager
        from app.utils.mcp_tool_builder import create_mcp_tools_from_definitions

        # Get toolkit from toolkit manager (will create if not exists)
        toolkit_manager = get_toolkit_manager()
        toolkit = await toolkit_manager.get_toolkit(server, server.user_id)

        # Get tool definitions (MCPTool objects)
        if not toolkit.session:
            raise RuntimeError(f"Toolkit session not initialized for server: {server.name}")

        available_tools = await toolkit.session.list_tools()  # type: ignore
        mcp_tool_definitions = available_tools.tools

        # Create EnhancedTools with lazy entrypoints
        # Use timeout from config (converted from server.timeout)
        timeout_seconds = config.timeout_seconds
        tools = create_mcp_tools_from_definitions(
            mcp_tools=mcp_tool_definitions,
            server_name=server.name,
            user_id=server.user_id,
            timeout_seconds=timeout_seconds,
        )

        return tools

    @staticmethod
    def config_from_server(server: McpServer) -> McpConnectionConfig:
        """
        Create a connection configuration from an McpServer model.

        Args:
            server: MCP server model

        Returns:
            McpConnectionConfig
        """
        if not server.url:
            raise ValueError("Server URL is required")
        return McpConnectionConfig(
            url=server.url,
            transport=server.transport or "streamable-http",
            timeout_seconds=(server.timeout or 30000) // 1000,
            headers=server.headers or {},
        )


# default client instance (can be replaced in tests)
_default_client: Optional[McpClientService] = None


def get_mcp_client() -> McpClientService:
    """Get the MCP client instance."""
    global _default_client
    if _default_client is None:
        _default_client = McpClientService()
    return _default_client
