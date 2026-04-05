"""
Tool Service — unified tool management service.

Responsibilities:
- Tool registration/unregistration (sync to ToolRegistry)
- Tool queries (read from ToolRegistry)
- Coordinate MCP server and tool synchronization

Design principles:
- Facade pattern: provide a single entry point for tool management
- Composition over inheritance: compose McpServerService and McpClientService
- Single responsibility: focus on tool management; MCP server CRUD is delegated to McpServerService
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException
from app.core.tools.tool import EnhancedTool, ToolFilter, ToolSourceType
from app.core.tools.tool_registry import ToolRegistry, get_global_registry
from app.models.enums import McpConnectionStatus
from app.models.mcp import McpServer
from app.schemas.mcp import (
    ConnectionTestResult,
    McpServerCreate,
    McpServerUpdate,
    ToolInfo,
)
from app.services.base import BaseService
from app.services.mcp_client_service import McpClientService, get_mcp_client
from app.services.mcp_server_service import McpServerService


class ToolService(BaseService[McpServer]):
    """
    Unified tool management service (Facade).

    Responsibilities:
    - Coordinate MCP server management and tool registration
    - Tool queries
    - Tool synchronization

    Composed services:
    - McpServerService: MCP server CRUD
    - McpClientService: MCP connection and tool fetching
    - ToolRegistry: tool registration center
    """

    def __init__(
        self,
        db: AsyncSession,
        mcp_client: Optional[McpClientService] = None,
    ):
        super().__init__(db)
        self._server_service = McpServerService(db)
        self._mcp_client = mcp_client or get_mcp_client()
        self._registry = get_global_registry()

    @property
    def registry(self) -> ToolRegistry:
        """Get the global tool registry."""
        return self._registry

    @property
    def server_service(self) -> McpServerService:
        """Get the MCP server service."""
        return self._server_service

    # ==================== MCP Server Operations (Delegate) ====================

    async def create_mcp_server(
        self,
        user_id: str,
        data: McpServerCreate,
    ) -> McpServer:
        """
        Create an MCP server and sync tools.
        """
        server = await self._server_service.create(user_id, data)

        # If enabled, sync tools
        if server.enabled:
            await self._sync_server_tools_safe(server)

        return server

    async def update_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
        data: McpServerUpdate,
    ) -> McpServer:
        """
        Update an MCP server and sync tools to the registry.

        Handling logic:
        1. Name change: unregister old-name tools first, then register new-name tools after update
        2. State change: enabled->disabled unregisters tools, disabled->enabled syncs tools
        3. Config change: if connection config changed, re-sync tools
        """
        # get current server state
        server = await self._server_service.get(server_id, user_id)
        old_name = server.name
        was_enabled = server.enabled

        # detect change types
        name_changed = data.name is not None and data.name != server.name
        needs_resync = self._server_service.needs_resync(data, server)

        # handle name change: unregister old-name tools first
        if name_changed and was_enabled:
            await self._unregister_server_tools_by_name(old_name, user_id)

        # execute update
        server = await self._server_service.update(server_id, user_id, data)
        will_be_enabled = server.enabled

        # handle tool sync logic
        await self._handle_tool_sync_after_update(
            server=server,
            was_enabled=was_enabled,
            will_be_enabled=will_be_enabled,
            name_changed=name_changed,
            needs_resync=needs_resync,
        )

        return server

    async def delete_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """
        Delete an MCP server and unregister its tools.
        """
        server = await self._server_service.get(server_id, user_id)
        await self._unregister_server_tools(server)
        return await self._server_service.delete(server_id, user_id)

    async def get_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> McpServer:
        """Get an MCP server."""
        return await self._server_service.get(server_id, user_id)

    async def list_mcp_servers(
        self,
        user_id: str,
        enabled_only: bool = False,
    ) -> List[McpServer]:
        """
        Get MCP server list (user-level).

        Args:
            user_id: user ID
            enabled_only: whether to return only enabled servers
        """
        return await self._server_service.list(user_id, enabled_only)

    async def toggle_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
        enabled: bool,
    ) -> McpServer:
        """
        Toggle MCP server enabled state.
        """
        server = await self._server_service.get(server_id, user_id)

        if server.enabled == enabled:
            return server

        server = await self._server_service.toggle_enabled(server_id, user_id, enabled)

        if enabled:
            await self._sync_server_tools_safe(server)
        else:
            await self._unregister_server_tools(server)

        return server

    # ==================== Connection & Tool Sync ====================

    async def test_connection(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> ConnectionTestResult:
        """
        Test MCP server connection.
        """
        server = await self._server_service.get(server_id, user_id)
        config = McpClientService.config_from_server(server)

        result = await self._mcp_client.test_connection(config, server)

        # Update server status
        if result.success:
            await self._server_service.update_connection_status(server_id, McpConnectionStatus.CONNECTED)
        else:
            await self._server_service.update_connection_status(server_id, McpConnectionStatus.ERROR, result.error)

        tool_names = [t.name for t in result.tools]

        return ConnectionTestResult(
            success=result.success,
            message=f"Connected successfully. Found {len(result.tools)} tools."
            if result.success
            else f"Connection failed: {result.error}",
            tool_count=len(result.tools),
            tools=tool_names,
            latency_ms=result.latency_ms,
        )

    async def refresh_server_tools(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> List[ToolInfo]:
        """
        Refresh MCP server tools.
        """
        server = await self._server_service.get(server_id, user_id)

        if not server.enabled:
            raise BadRequestException("Cannot refresh tools for disabled server")

        return await self._sync_server_tools(server)

    async def sync_all_tools_for_user(
        self,
        user_id: str,
    ) -> int:
        """
        Sync all enabled MCP server tools for a user (user-level).

        Args:
            user_id: user ID
        """
        servers = await self._server_service.list(user_id, enabled_only=True)

        total_tools = 0
        for server in servers:
            try:
                tools = await self._sync_server_tools(server)
                total_tools += len(tools)
            except Exception as e:
                logger.error(f"Failed to sync tools for server {server.name}: {e}")

        return total_tools

    # ==================== Tool Queries ====================

    def get_available_tools(
        self,
        user_id: str,
        tool_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[ToolInfo]:
        """
        Get available tools for a user (user-level).

        Args:
            user_id: user ID
            tool_type: tool type filter
            category: category filter
        """
        filter_config = self._build_filter(tool_type, category)

        tools = self._registry.get_tools_for_scope(
            user_id=user_id,
            workspace_id=None,  # user-level, no workspace
            filter_config=filter_config,
            include_builtin=True,
        )

        return [self._tool_to_info(t) for t in tools]

    def get_builtin_tools(self) -> List[ToolInfo]:
        """Get all built-in tools."""
        tools = self._registry.get_tools(ToolFilter(source_types={ToolSourceType.BUILTIN}))
        return [self._tool_to_info(t) for t in tools]

    def get_tool_by_key(self, tool_key: str) -> Optional[ToolInfo]:
        """Get tool info by tool key."""
        tool = self._registry.get_tool(tool_key)
        return self._tool_to_info(tool) if tool else None

    def get_mcp_tool(self, server_name: str, tool_name: str) -> Optional[ToolInfo]:
        """Get an MCP tool."""
        tool = self._registry.get_mcp_tool(server_name, tool_name)
        return self._tool_to_info(tool) if tool else None

    async def get_server_tools(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> List[ToolInfo]:
        """
        Get the tool list for an MCP server.

        Verify permissions first, then fetch tools from the Registry.
        """
        # verify permissions
        server = await self._server_service.get(server_id, user_id)

        # fetch tools for this server from the Registry
        tools = self._registry.get_mcp_server_tools(server.name)
        return [self._tool_to_info(t) for t in tools]

    # ==================== Private Helpers: Tool Sync Logic ====================

    async def _handle_tool_sync_after_update(
        self,
        server: McpServer,
        was_enabled: bool,
        will_be_enabled: bool,
        name_changed: bool,
        needs_resync: bool,
    ) -> None:
        """
        Handle tool sync logic after an update.

        Args:
            server: the updated server object
            was_enabled: enabled state before the update
            will_be_enabled: enabled state after the update
            name_changed: whether the name changed
            needs_resync: whether a re-sync is needed (config change)
        """
        # case 1: enabled -> disabled — unregister tools
        if not will_be_enabled and was_enabled:
            if not name_changed:  # name unchanged, unregister by new name
                await self._unregister_server_tools(server)
            # if name changed, old-name tools were already unregistered before the update

        # case 2: stays or becomes enabled — sync tools based on conditions
        elif will_be_enabled:
            should_sync = (
                needs_resync  # config changed, needs re-sync
                or name_changed  # name changed, needs to register new-name tools
                or not was_enabled  # disabled -> enabled, needs sync
            )
            if should_sync:
                await self._sync_server_tools_safe(server)

    async def _sync_server_tools_safe(self, server: McpServer) -> None:
        """Safely sync server tools (catch exceptions)."""
        try:
            await self._sync_server_tools(server)
        except Exception as e:
            logger.warning(f"Failed to sync tools for server {server.name}: {e}")

    async def _sync_server_tools(self, server: McpServer) -> List[ToolInfo]:
        """Sync server tools to the Registry."""
        config = McpClientService.config_from_server(server)

        try:
            result = await self._mcp_client.connect_and_fetch_tools(config, server)

            if not result.success:
                await self._server_service.update_connection_status(server.id, McpConnectionStatus.ERROR, result.error)
                raise Exception(result.error)

            # Unregister old tools
            await self._unregister_server_tools(server)

            # Register new tools (user-level only)
            registered = self._registry.register_mcp_tools(
                mcp_server_name=server.name,
                tools=result.tools,
                owner_user_id=server.user_id,
                owner_workspace_id=None,  # user-level, no workspace
                category="mcp",
            )

            # Update server stats
            await self._server_service.update_tool_count(server.id, len(registered))
            await self._server_service.update_connection_status(server.id, McpConnectionStatus.CONNECTED)

            return [self._tool_to_info(t) for t in registered]

        except Exception as e:
            await self._server_service.update_connection_status(server.id, McpConnectionStatus.ERROR, str(e))
            raise

    # ==================== Private Helpers: Registry Operations ====================

    async def _unregister_server_tools(self, server: McpServer) -> int:
        """
        Unregister all tools for a server from the Registry, and close the corresponding Toolkit.

        Args:
            server: MCP server object

        Returns:
            Number of tools unregistered
        """
        count = self._registry.unregister_mcp_server_tools(server.name)
        if count > 0:
            logger.info(f"Unregistered {count} tools from server: {server.name}")

        # close the corresponding Toolkit
        from app.services.mcp_toolkit_manager import get_toolkit_manager

        toolkit_manager = get_toolkit_manager()
        try:
            await toolkit_manager.close_toolkit(server.name, server.user_id)
        except Exception as e:
            logger.warning(f"Failed to close toolkit for server {server.name}: {e}")

        return count

    async def _unregister_server_tools_by_name(self, server_name: str, user_id: str) -> int:
        """
        Unregister tools by server name (for name-change scenarios), and close the corresponding Toolkit.

        Args:
            server_name: server name
            user_id: user ID

        Returns:
            Number of tools unregistered
        """
        count = self._registry.unregister_mcp_server_tools(server_name)
        if count > 0:
            logger.info(f"Unregistered {count} tools from server: {server_name}")

        # close the corresponding Toolkit
        from app.services.mcp_toolkit_manager import get_toolkit_manager

        toolkit_manager = get_toolkit_manager()
        try:
            await toolkit_manager.close_toolkit(server_name, user_id)
        except Exception as e:
            logger.warning(f"Failed to close toolkit for server {server_name}: {e}")

        return count

    # ==================== Private Helpers: Tool Conversion ====================

    def _build_filter(
        self,
        tool_type: Optional[str],
        category: Optional[str],
    ) -> Optional[ToolFilter]:
        """Build a tool filter."""
        if not tool_type and not category:
            return None

        filter_config = ToolFilter()

        if tool_type:
            try:
                source_type = ToolSourceType(tool_type)
                filter_config.source_types = {source_type}
            except ValueError:
                pass

        if category:
            filter_config.categories = {category}

        return filter_config

    def _tool_to_info(self, tool: EnhancedTool) -> ToolInfo:
        """
        Convert an EnhancedTool to ToolInfo.

        Args:
            tool: EnhancedTool instance

        Returns:
            ToolInfo object
        """
        metadata = tool.tool_metadata
        tool_type = metadata.custom_attrs.get("tool_type", metadata.source_type.value)

        label_name = tool.get_label_name()
        real_name = tool.name

        return ToolInfo(
            id=label_name,
            name=real_name,
            label_name=label_name,
            description=tool.description or "",
            tool_type=tool_type,
            category=metadata.category,
            tags=list(metadata.tags),
            mcp_server=metadata.mcp_server_name,
            mcp_tool_name=metadata.mcp_tool_name,
            owner_user_id=metadata.owner_user_id,
            owner_workspace_id=None,  # user-level, no longer uses workspace
            enabled=metadata.enabled,
        )


# ==================== Startup Hook ====================

# ==================== Startup Hook ====================


async def initialize_mcp_tools_on_startup(
    db: AsyncSession,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    allow_partial_failure: bool = True,
) -> int:
    """
    Load all enabled MCP server tools into the global registry at application startup.

    Flow:
    1. Query all enabled MCP servers
    2. Connect to each server and fetch tool lists (with retry mechanism)
    3. Register tools into the global ToolRegistry
    4. Update server connection status and tool count

    Args:
        db: database session
        max_retries: max retry count per server on connection failure
        retry_delay: retry delay (seconds), using exponential backoff
        allow_partial_failure: if True, a single server failure does not affect others

    Returns:
        Total number of tools loaded
    """
    import asyncio

    from app.services.mcp_server_service import McpServerService

    server_service = McpServerService(db)
    mcp_client = get_mcp_client()
    registry = get_global_registry()

    servers = await server_service.list_all_enabled()
    logger.info(f"Loading tools from {len(servers)} enabled MCP servers...")

    total_tools = 0
    successful_servers = 0
    failed_servers = 0

    for server in servers:
        retry_count = 0

        while retry_count <= max_retries:
            try:
                config = McpClientService.config_from_server(server)
                result = await mcp_client.connect_and_fetch_tools(config, server)

                if result.success:
                    registered = registry.register_mcp_tools(
                        mcp_server_name=server.name,
                        tools=result.tools,
                        owner_user_id=server.user_id,
                        owner_workspace_id=None,  # user-level, no workspace
                        category="mcp",
                    )

                    await server_service.update_tool_count(server.id, len(registered))
                    await server_service.update_connection_status(server.id, McpConnectionStatus.CONNECTED)

                    total_tools += len(registered)
                    successful_servers += 1
                    logger.info(
                        f"Loaded {len(registered)} tools from MCP server: {server.name} (user_id={server.user_id})"
                    )
                    break  # Success, exit retry loop
                else:
                    if retry_count < max_retries:
                        retry_count += 1
                        delay = retry_delay * (2 ** (retry_count - 1))  # Exponential backoff
                        logger.warning(
                            f"Failed to load tools from MCP server {server.name} "
                            f"(attempt {retry_count}/{max_retries}): {result.error}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        # Max retries reached
                        await server_service.update_connection_status(server.id, McpConnectionStatus.ERROR, result.error)
                        failed_servers += 1
                        logger.error(
                            f"Failed to load tools from MCP server {server.name} after {max_retries} retries: "
                            f"{result.error}"
                        )
                        if not allow_partial_failure:
                            raise Exception(f"Failed to load tools from MCP server {server.name}: {result.error}")
                        break

            except Exception as e:
                str(e)
                if retry_count < max_retries:
                    retry_count += 1
                    delay = retry_delay * (2 ** (retry_count - 1))  # Exponential backoff
                    logger.warning(
                        f"Exception loading tools from MCP server {server.name} "
                        f"(attempt {retry_count}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f}s...",
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
                else:
                    # Max retries reached
                    await server_service.update_connection_status(server.id, McpConnectionStatus.ERROR, str(e))
                    failed_servers += 1
                    logger.error(
                        f"Failed to load tools from MCP server {server.name} after {max_retries} retries: {e}",
                        exc_info=True,
                    )
                    if not allow_partial_failure:
                        raise
                    break

    await db.commit()
    logger.info(
        f"MCP tools startup summary: {total_tools} tools loaded from {successful_servers} servers, "
        f"{failed_servers} servers failed"
    )
    return total_tools
