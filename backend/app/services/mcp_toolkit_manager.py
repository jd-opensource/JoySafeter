"""
MCP Toolkit Manager

Maintain a pool of active MCPTools instances, one persistent Toolkit instance per server.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

from loguru import logger

from app.core.tools.mcp.mcp import MCPTools
from app.models.mcp import McpServer


class McpToolkitManager:
    """
    MCP Toolkit manager.

    Maintain a pool of active MCPTools instances, keyed by (user_id, server_name).
    Each Toolkit instance maintains its own session connection internally.
    """

    def __init__(self):
        # storage format: (user_id, server_name) -> MCPTools instance
        self._toolkits: Dict[Tuple[str, str], MCPTools] = {}
        self._lock = asyncio.Lock()
        self._server_configs: Dict[Tuple[str, str], McpServer] = {}

    async def get_toolkit(
        self,
        server: McpServer,
        user_id: str,
    ) -> MCPTools:
        """
        Get or create an MCPTools instance.

        Args:
            server: MCP server configuration
            user_id: user ID

        Returns:
            MCPTools: active Toolkit instance
        """
        key = (user_id, server.name)

        async with self._lock:
            # check if an active instance already exists
            if key in self._toolkits:
                toolkit = self._toolkits[key]
                # check if config changed (requires reconnection)
                cached_config = self._server_configs.get(key)
                if cached_config and self._config_changed(cached_config, server):
                    logger.info(f"Server config changed for {server.name}, closing old toolkit")
                    await self._close_toolkit_internal(key, toolkit)
                    # continue to create a new instance
                else:
                    # verify the connection is still alive
                    if toolkit.session:
                        try:
                            await toolkit.session.send_ping()
                            return toolkit
                        except Exception as e:
                            logger.warning(f"Toolkit ping failed for {server.name}, reconnecting: {e}")
                            await self._close_toolkit_internal(key, toolkit)

            # create a new Toolkit instance
            logger.info(f"Creating new MCPTools instance for server: {server.name} (user: {user_id})")
            toolkit = await self._create_toolkit(server)
            self._toolkits[key] = toolkit
            self._server_configs[key] = server

            return toolkit

    async def _create_toolkit(self, server: McpServer) -> MCPTools:
        """
        Create a new MCPTools instance.

        Returns:
            MCPTools instance
        """
        transport = server.transport or "streamable-http"
        timeout_seconds = (server.timeout or 30000) // 1000

        toolkit = MCPTools(
            url=server.url,
            transport=transport,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
        )

        # connect and initialize
        await toolkit.connect()

        return toolkit

    async def _close_toolkit_internal(
        self,
        key: Tuple[str, str],
        toolkit: MCPTools,
    ) -> None:
        """Internal method: close a toolkit (caller does not hold the lock)."""
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
        Close the Toolkit for a specific server.

        Args:
            server_name: server name
            user_id: user ID
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
        Close all Toolkit instances for a user.

        Args:
            user_id: user ID
        """
        async with self._lock:
            keys_to_close = [key for key in self._toolkits.keys() if key[0] == user_id]

            for key in keys_to_close:
                toolkit = self._toolkits[key]
                await self._close_toolkit_internal(key, toolkit)

            if keys_to_close:
                logger.info(f"Closed {len(keys_to_close)} MCPTools instances for user: {user_id}")

    async def cleanup_all(self) -> None:
        """Close all active Toolkit instances (for shutdown cleanup)."""
        async with self._lock:
            keys_to_close = list(self._toolkits.keys())

            for key in keys_to_close:
                toolkit = self._toolkits[key]
                await self._close_toolkit_internal(key, toolkit)

            if keys_to_close:
                logger.info(f"Cleaned up {len(keys_to_close)} MCPTools instances")

    def _config_changed(self, old_config: McpServer, new_config: McpServer) -> bool:
        """Check whether the server configuration has changed."""
        return (
            old_config.url != new_config.url
            or old_config.transport != new_config.transport
            or old_config.headers != new_config.headers
            or old_config.timeout != new_config.timeout
        )


# global toolkit manager instance
_global_toolkit_manager: Optional[McpToolkitManager] = None


def get_toolkit_manager() -> McpToolkitManager:
    """Get the global toolkit manager instance."""
    global _global_toolkit_manager
    if _global_toolkit_manager is None:
        _global_toolkit_manager = McpToolkitManager()
    return _global_toolkit_manager
