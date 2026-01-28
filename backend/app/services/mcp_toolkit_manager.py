"""
MCP Toolkit Manager - MCP Toolkit 管理器

维护活跃的 MCPTools 实例池，每个服务器对应一个持久的 Toolkit 实例。
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

from loguru import logger

from app.core.tools.mcp.mcp import MCPTools
from app.models.mcp import McpServer


class McpToolkitManager:
    """
    MCP Toolkit 管理器

    维护活跃的 MCPTools 实例池，按 (user_id, server_name) 唯一标识。
    每个 Toolkit 实例内部维护自己的 session 连接。
    """

    def __init__(self):
        # 存储格式: (user_id, server_name) -> MCPTools 实例
        self._toolkits: Dict[Tuple[str, str], MCPTools] = {}
        self._lock = asyncio.Lock()
        self._server_configs: Dict[Tuple[str, str], McpServer] = {}

    async def get_toolkit(
        self,
        server: McpServer,
        user_id: str,
    ) -> MCPTools:
        """
        获取或创建 MCPTools 实例

        Args:
            server: MCP 服务器配置
            user_id: 用户 ID

        Returns:
            MCPTools: 活跃的 Toolkit 实例
        """
        key = (user_id, server.name)

        async with self._lock:
            # 检查是否已有活跃实例
            if key in self._toolkits:
                toolkit = self._toolkits[key]
                # 检查配置是否变更（需要重新连接）
                cached_config = self._server_configs.get(key)
                if cached_config and self._config_changed(cached_config, server):
                    logger.info(f"Server config changed for {server.name}, closing old toolkit")
                    await self._close_toolkit_internal(key, toolkit)
                    # 继续创建新实例
                else:
                    # 验证连接是否仍然有效
                    if toolkit.session:
                        try:
                            await toolkit.session.send_ping()
                            return toolkit
                        except Exception as e:
                            logger.warning(f"Toolkit ping failed for {server.name}, reconnecting: {e}")
                            await self._close_toolkit_internal(key, toolkit)

            # 创建新 Toolkit 实例
            logger.info(f"Creating new MCPTools instance for server: {server.name} (user: {user_id})")
            toolkit = await self._create_toolkit(server)
            self._toolkits[key] = toolkit
            self._server_configs[key] = server

            return toolkit

    async def _create_toolkit(self, server: McpServer) -> MCPTools:
        """
        创建新的 MCPTools 实例

        Returns:
            MCPTools 实例
        """
        transport = server.transport or "streamable-http"
        timeout_seconds = (server.timeout or 30000) // 1000

        toolkit = MCPTools(
            url=server.url,
            transport=transport,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
        )

        # 连接并初始化
        await toolkit.connect()

        return toolkit

    async def _close_toolkit_internal(
        self,
        key: Tuple[str, str],
        toolkit: MCPTools,
    ) -> None:
        """内部方法：关闭 toolkit（不持有锁）"""
        try:
            await toolkit.close()
        except Exception as e:
            logger.error(f"Error closing toolkit for {key}: {e}")
        finally:
            if key in self._toolkits:
                del self._toolkits[key]
            if key in self._server_configs:
                del self._server_configs[key]

    async def close_toolkit(
        self,
        server_name: str,
        user_id: str,
    ) -> None:
        """
        关闭指定服务器的 Toolkit

        Args:
            server_name: 服务器名称
            user_id: 用户 ID
        """
        key = (user_id, server_name)

        async with self._lock:
            if key not in self._toolkits:
                return

            toolkit = self._toolkits[key]
            await self._close_toolkit_internal(key, toolkit)
            logger.info(f"Closed MCPTools instance for server: {server_name} (user: {user_id})")

    async def close_all_user_toolkits(self, user_id: str) -> None:
        """
        关闭用户的所有 Toolkit 实例

        Args:
            user_id: 用户 ID
        """
        async with self._lock:
            keys_to_close = [key for key in self._toolkits.keys() if key[0] == user_id]

            for key in keys_to_close:
                toolkit = self._toolkits[key]
                await self._close_toolkit_internal(key, toolkit)

            if keys_to_close:
                logger.info(f"Closed {len(keys_to_close)} MCPTools instances for user: {user_id}")

    async def cleanup_all(self) -> None:
        """关闭所有活跃的 Toolkit 实例（用于关闭时清理）"""
        async with self._lock:
            keys_to_close = list(self._toolkits.keys())

            for key in keys_to_close:
                toolkit = self._toolkits[key]
                await self._close_toolkit_internal(key, toolkit)

            if keys_to_close:
                logger.info(f"Cleaned up {len(keys_to_close)} MCPTools instances")

    def _config_changed(self, old_config: McpServer, new_config: McpServer) -> bool:
        """检查服务器配置是否变更"""
        return (
            old_config.url != new_config.url
            or old_config.transport != new_config.transport
            or old_config.headers != new_config.headers
            or old_config.timeout != new_config.timeout
        )


# 全局 toolkit manager 实例
_global_toolkit_manager: Optional[McpToolkitManager] = None


def get_toolkit_manager() -> McpToolkitManager:
    """获取全局 toolkit manager 实例"""
    global _global_toolkit_manager
    if _global_toolkit_manager is None:
        _global_toolkit_manager = McpToolkitManager()
    return _global_toolkit_manager


async def cleanup_all_toolkits() -> None:
    """清理所有 toolkits（用于应用关闭时）"""
    global _global_toolkit_manager
    if _global_toolkit_manager:
        await _global_toolkit_manager.cleanup_all()
