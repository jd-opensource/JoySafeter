"""
MCP Server Service — MCP server management service.

Responsibility: CRUD operations for MCP server configuration.
Single responsibility: only handle database persistence of server configuration.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.enums import McpConnectionStatus
from app.models.mcp import McpServer
from app.repositories.mcp_server import McpServerRepository
from app.schemas.mcp import McpServerCreate, McpServerUpdate
from app.services.base import BaseService


class McpServerService(BaseService[McpServer]):
    """
    MCP server management service.

    Responsibilities:
    - CRUD for MCP server configuration
    - Does not handle tool registration (delegated to ToolService)

    Design principles:
    - Single responsibility: only manage server configuration
    - High cohesion: all methods relate to server configuration
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = McpServerRepository(db)

    # ==================== CRUD Operations ====================

    async def create(
        self,
        user_id: str,
        data: McpServerCreate,
    ) -> McpServer:
        """
        Create an MCP server.

        Args:
            user_id: user ID
            data: creation data

        Returns:
            The created MCP server
        """
        logger.info(f"[McpServerService] create - user_id={user_id}, name={data.name}")

        # Check name uniqueness
        existing = await self.repo.get_by_name(user_id, data.name)
        if existing:
            logger.warning(f"[McpServerService] Duplicate name: {data.name} for user {user_id}")
            raise BadRequestException(f"MCP server with name '{data.name}' already exists")

        server = await self.repo.create(
            {
                "user_id": user_id,
                "created_by": user_id,
                "name": data.name,
                "description": data.description,
                "transport": data.transport,
                "url": data.url,
                "headers": data.headers,
                "timeout": data.timeout,
                "retries": data.retries,
                "enabled": data.enabled,
                "connection_status": McpConnectionStatus.DISCONNECTED,
            }
        )

        await self.commit()
        logger.info(f"Created MCP server: {server.name} (id={server.id})")
        return server

    async def update(
        self,
        server_id: uuid.UUID,
        user_id: str,
        data: McpServerUpdate,
    ) -> McpServer:
        """
        Update MCP server configuration.

        Args:
            server_id: server ID
            user_id: user ID
            data: update data

        Returns:
            The updated MCP server
        """
        server = await self.get_with_permission(server_id, user_id)

        # Check name uniqueness if changing
        if data.name and data.name != server.name:
            existing = await self.repo.get_by_name(user_id, data.name)
            if existing:
                raise BadRequestException(f"MCP server with name '{data.name}' already exists")

        # Build update dict
        update_data = {}
        for field in ["name", "description", "transport", "url", "headers", "timeout", "retries", "enabled"]:
            value = getattr(data, field, None)
            if value is not None:
                update_data[field] = value

        if not update_data:
            return server

        updated_server = await self.repo.update(server_id, update_data)
        if updated_server is None:
            raise ValueError(f"MCP server {server_id} not found")
        await self.commit()
        logger.info(f"Updated MCP server: {updated_server.name}")
        return updated_server

    async def delete(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> bool:
        """
        Delete an MCP server (hard delete).

        Args:
            server_id: server ID
            user_id: user ID

        Returns:
            Whether the deletion succeeded
        """
        server = await self.get_with_permission(server_id, user_id)

        # hard delete: remove the record entirely to avoid unique constraints occupied by soft-deleted rows
        result = await self.repo.delete(server_id)
        await self.commit()
        logger.info(f"Deleted MCP server: {server.name}")
        return result

    async def get(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> McpServer:
        """
        Get an MCP server.

        Args:
            server_id: server ID
            user_id: user ID

        Returns:
            MCP server
        """
        return await self.get_with_permission(server_id, user_id)

    async def get_by_id(self, server_id: uuid.UUID) -> Optional[McpServer]:
        """
        Get a server by ID (no permission check, internal use).

        Args:
            server_id: server ID

        Returns:
            MCP server or None
        """
        server = await self.repo.get(server_id)
        if server and server.deleted_at:
            return None
        return server

    async def list(
        self,
        user_id: str,
        enabled_only: bool = False,
    ) -> List[McpServer]:
        """
        Get the list of MCP servers accessible to a user (user-level).

        Args:
            user_id: user ID
            enabled_only: whether to return only enabled servers

        Returns:
            MCP server list
        """
        return await self.repo.find_for_user_scope(
            user_id=user_id,
            enabled_only=enabled_only,
        )

    async def list_all_enabled(self) -> List[McpServer]:
        """
        Get all enabled servers (for startup loading).

        Returns:
            All enabled MCP servers
        """
        return await self.repo.find_all_enabled()

    # ==================== Status Operations ====================

    async def toggle_enabled(
        self,
        server_id: uuid.UUID,
        user_id: str,
        enabled: bool,
    ) -> McpServer:
        """
        Toggle enabled state.

        Args:
            server_id: server ID
            user_id: user ID
            enabled: whether to enable

        Returns:
            The updated MCP server
        """
        server = await self.get_with_permission(server_id, user_id)

        if server.enabled == enabled:
            return server

        updated_server = await self.repo.toggle_enabled(server_id, enabled)
        if updated_server is None:
            raise ValueError(f"MCP server {server_id} not found")
        await self.commit()
        logger.info(f"MCP server {updated_server.name} {'enabled' if enabled else 'disabled'}")
        return updated_server

    async def update_connection_status(
        self,
        server_id: uuid.UUID,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[McpServer]:
        """
        Update connection status.

        Args:
            server_id: server ID
            status: connection status
            error: error message

        Returns:
            The updated MCP server
        """
        server = await self.repo.update_connection_status(server_id, status, error)
        await self.commit()
        return server

    async def update_tool_count(
        self,
        server_id: uuid.UUID,
        tool_count: int,
    ) -> Optional[McpServer]:
        """
        Update tool count.

        Args:
            server_id: server ID
            tool_count: tool count

        Returns:
            The updated MCP server
        """
        server = await self.repo.update_tool_count(server_id, tool_count)
        await self.commit()
        return server

    # ==================== Helper Methods ====================

    async def get_with_permission(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> McpServer:
        """
        Get a server and check permissions.

        Args:
            server_id: server ID
            user_id: user ID

        Returns:
            MCP server

        Raises:
            NotFoundException: server does not exist or no permission
        """
        server = await self.repo.get(server_id)

        if not server or server.deleted_at:
            raise NotFoundException("MCP server not found")

        if server.user_id != user_id:
            raise NotFoundException("MCP server not found")  # Security: don't reveal existence

        return server

    def needs_resync(self, update_data: McpServerUpdate, server: McpServer) -> bool:
        """
        Determine whether an update requires re-syncing tools.

        Args:
            update_data: update data
            server: current server

        Returns:
            Whether a re-sync is needed
        """
        resync_fields = ["transport", "url", "headers"]
        for field in resync_fields:
            value = getattr(update_data, field, None)
            if value is not None and value != getattr(server, field):
                return True
        return False

    async def get_by_ids(
        self,
        server_ids: List[uuid.UUID],
        user_id: Optional[str] = None,
    ) -> Dict[uuid.UUID, McpServer]:
        """
        Batch-fetch MCP servers (for tool resolution).

        Args:
            server_ids: list of server IDs
            user_id: optional user ID (for permission filtering)

        Returns:
            UUID -> McpServer mapping dict
        """
        return await self.repo.get_by_ids(server_ids, user_id)
