"""
MCP Server Repository

Manage user-level and workspace-level MCP servers.
"""

import uuid
from typing import Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp import McpServer
from app.repositories.base import BaseRepository


class McpServerRepository(BaseRepository[McpServer]):
    """
    MCP Server Repository

    Provide user/workspace-level CRUD operations for MCP servers.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(McpServer, db)

    async def find_by_user(
        self,
        user_id: str,
        enabled_only: bool = False,
        include_deleted: bool = False,
    ) -> List[McpServer]:
        """
        Return all MCP servers owned by the user.

        Args:
            user_id: user ID
            enabled_only: only return enabled servers
            include_deleted: include soft-deleted records

        Returns:
            list of MCP servers
        """
        conditions = [
            McpServer.user_id == user_id,
        ]

        if enabled_only:
            conditions.append(McpServer.enabled.is_(True))  # type: ignore[arg-type]

        if not include_deleted:
            conditions.append(McpServer.deleted_at.is_(None))

        query = select(McpServer).where(and_(*conditions)).order_by(McpServer.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_for_user_scope(
        self,
        user_id: str,
        enabled_only: bool = False,
        include_deleted: bool = False,
    ) -> List[McpServer]:
        """
        Return all MCP servers accessible to the user (user scope).

        Args:
            user_id: user ID
            enabled_only: only return enabled servers
            include_deleted: include soft-deleted records

        Returns:
            list of MCP servers
        """
        return await self.find_by_user(user_id, enabled_only, include_deleted)

    async def find_enabled(
        self,
        user_id: Optional[str] = None,
    ) -> List[McpServer]:
        """
        Return enabled MCP servers.

        Args:
            user_id: user ID (optional)

        Returns:
            list of enabled MCP servers
        """
        conditions = [
            McpServer.enabled,
            McpServer.deleted_at.is_(None),
        ]

        if user_id:
            conditions.append(McpServer.user_id == user_id)  # type: ignore[arg-type]

        query = select(McpServer).where(and_(*conditions)).order_by(McpServer.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_all_enabled(self) -> List[McpServer]:
        """
        Return all enabled MCP servers (used at application startup).

        Returns:
            list of all enabled MCP servers
        """
        query = (
            select(McpServer)
            .where(
                and_(
                    McpServer.enabled,
                    McpServer.deleted_at.is_(None),
                )
            )
            .order_by(McpServer.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_name(
        self,
        user_id: str,
        name: str,
    ) -> Optional[McpServer]:
        """
        Get a server by user ID and server name.

        Args:
            user_id: user ID
            name: server name

        Returns:
            MCP server or None
        """
        query = select(McpServer).where(
            and_(
                McpServer.user_id == user_id,
                McpServer.name == name,
                McpServer.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

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
            status: connection status (connected, disconnected, error)
            error: error message (optional)

        Returns:
            updated MCP server
        """
        from datetime import datetime

        update_data = {
            "connection_status": status,
            "last_error": error,
        }

        if status == "connected":
            update_data["last_connected"] = datetime.utcnow()  # type: ignore[assignment]  # naive datetime for TIMESTAMP WITHOUT TIME ZONE
            update_data["last_error"] = None

        return await self.update(server_id, update_data)

    async def update_tool_count(
        self,
        server_id: uuid.UUID,
        tool_count: int,
    ) -> Optional[McpServer]:
        """
        Update tool count.

        Args:
            server_id: server ID
            tool_count: number of tools

        Returns:
            updated MCP server
        """
        from datetime import datetime

        update_data = {
            "tool_count": tool_count,
            "last_tools_refresh": datetime.utcnow(),  # naive datetime for TIMESTAMP WITHOUT TIME ZONE
        }

        return await self.update(server_id, update_data)

    async def toggle_enabled(
        self,
        server_id: uuid.UUID,
        enabled: bool,
    ) -> Optional[McpServer]:
        """
        Toggle enabled state.

        Args:
            server_id: server ID
            enabled: whether to enable

        Returns:
            updated MCP server
        """
        return await self.update(server_id, {"enabled": enabled})

    async def get_by_ids(
        self,
        server_ids: List[uuid.UUID],
        user_id: Optional[str] = None,
    ) -> Dict[uuid.UUID, McpServer]:
        """
        Batch-fetch MCP servers (for UUID resolution).

        Args:
            server_ids: list of server IDs
            user_id: optional user ID filter (permission check)

        Returns:
            mapping of UUID to McpServer
        """
        if not server_ids:
            return {}

        conditions = [
            McpServer.id.in_(server_ids),
            McpServer.deleted_at.is_(None),
        ]

        if user_id:
            conditions.append(McpServer.user_id == user_id)  # type: ignore[arg-type]

        query = select(McpServer).where(and_(*conditions))
        result = await self.db.execute(query)
        servers = list(result.scalars().all())

        # Return as dictionary mapping UUID to McpServer
        return {server.id: server for server in servers}
