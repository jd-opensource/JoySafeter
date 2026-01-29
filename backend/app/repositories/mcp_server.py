"""
MCP Server Repository - MCP 服务器数据访问层

支持用户级别和工作区级别的 MCP 服务器管理
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

    提供用户/工作区级别的 MCP 服务器 CRUD 操作
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
        获取用户拥有的所有 MCP 服务器

        Args:
            user_id: 用户 ID
            enabled_only: 是否只返回启用的服务器
            include_deleted: 是否包含已删除的记录

        Returns:
            MCP 服务器列表
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
        获取用户可访问的所有 MCP 服务器（用户级别）

        Args:
            user_id: 用户 ID
            enabled_only: 是否只返回启用的服务器
            include_deleted: 是否包含已删除的记录

        Returns:
            MCP 服务器列表
        """
        return await self.find_by_user(user_id, enabled_only, include_deleted)

    async def find_enabled(
        self,
        user_id: Optional[str] = None,
    ) -> List[McpServer]:
        """
        获取启用的 MCP 服务器

        Args:
            user_id: 用户 ID (可选)

        Returns:
            启用的 MCP 服务器列表
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
        获取所有启用的 MCP 服务器（用于应用启动时加载）

        Returns:
            所有启用的 MCP 服务器列表
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
        根据用户 ID 和服务器名称获取服务器

        Args:
            user_id: 用户 ID
            name: 服务器名称

        Returns:
            MCP 服务器或 None
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
        更新连接状态

        Args:
            server_id: 服务器 ID
            status: 连接状态 (connected, disconnected, error)
            error: 错误信息 (可选)

        Returns:
            更新后的 MCP 服务器
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
        更新工具数量

        Args:
            server_id: 服务器 ID
            tool_count: 工具数量

        Returns:
            更新后的 MCP 服务器
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
        切换启用状态

        Args:
            server_id: 服务器 ID
            enabled: 是否启用

        Returns:
            更新后的 MCP 服务器
        """
        return await self.update(server_id, {"enabled": enabled})

    async def increment_request_count(
        self,
        server_id: uuid.UUID,
    ) -> Optional[McpServer]:
        """
        增加请求计数

        Args:
            server_id: 服务器 ID

        Returns:
            更新后的 MCP 服务器
        """
        from datetime import datetime

        server = await self.get(server_id)
        if not server:
            return None

        update_data = {
            "total_requests": (server.total_requests or 0) + 1,
            "last_used": datetime.utcnow(),  # naive datetime for TIMESTAMP WITHOUT TIME ZONE
        }

        return await self.update(server_id, update_data)

    async def get_by_ids(
        self,
        server_ids: List[uuid.UUID],
        user_id: Optional[str] = None,
    ) -> Dict[uuid.UUID, McpServer]:
        """
        批量获取 MCP 服务器（用于 UUID 解析）

        Args:
            server_ids: 服务器 ID 列表
            user_id: 可选的用户 ID 过滤（权限检查）

        Returns:
            UUID -> McpServer 的映射字典
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
