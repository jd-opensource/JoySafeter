"""
MCP Client Service - MCP 客户端服务

封装与 MCP 服务器的连接、工具获取等底层操作
职责单一：只负责 MCP 协议层面的交互
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
    """MCP 连接配置"""

    url: str
    transport: str = "streamable-http"
    timeout_seconds: int = 30
    headers: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}


@dataclass
class McpConnectionResult:
    """MCP 连接结果"""

    success: bool
    tools: List[EnhancedTool]
    error: Optional[str] = None
    latency_ms: Optional[float] = None


@runtime_checkable
class IMcpClient(Protocol):
    """MCP 客户端接口 - 用于依赖注入和测试"""

    async def connect_and_fetch_tools(
        self,
        config: McpConnectionConfig,
    ) -> McpConnectionResult:
        """连接到 MCP 服务器并获取工具列表"""
        ...

    async def test_connection(
        self,
        config: McpConnectionConfig,
    ) -> McpConnectionResult:
        """测试连接"""
        ...


class McpClientService:
    """
    MCP 客户端服务

    封装与 MCP 服务器的底层交互：
    - 连接管理
    - 工具获取
    - 连接测试

    设计原则：
    - 单一职责：只负责 MCP 协议交互
    - 可测试：通过 IMcpClient 协议支持 mock
    - 可扩展：支持不同的 transport 类型
    """

    async def connect_and_fetch_tools(
        self,
        config: McpConnectionConfig,
        server: McpServer,
    ) -> McpConnectionResult:
        """
        连接到 MCP 服务器并获取工具列表

        Args:
            config: 连接配置
            server: MCP 服务器对象

        Returns:
            McpConnectionResult 包含工具列表或错误信息
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
        测试 MCP 服务器连接

        Args:
            config: 连接配置
            server: MCP 服务器对象（可选，用于测试连接前）

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
        从 MCP 服务器获取工具定义并创建 EnhancedTool 列表

        Args:
            config: 连接配置（主要使用 timeout_seconds）
            server: MCP 服务器对象

        Returns:
            工具列表（使用 lazy entrypoint）
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
        从 McpServer 模型创建连接配置

        Args:
            server: MCP 服务器模型

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


# 默认客户端实例（可在测试中替换）
_default_client: Optional[McpClientService] = None


def get_mcp_client() -> McpClientService:
    """获取 MCP 客户端实例"""
    global _default_client
    if _default_client is None:
        _default_client = McpClientService()
    return _default_client


def set_mcp_client(client: McpClientService) -> None:
    """设置 MCP 客户端实例（用于测试）"""
    global _default_client
    _default_client = client
