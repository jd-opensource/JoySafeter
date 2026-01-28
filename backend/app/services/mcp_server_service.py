"""
MCP Server Service - MCP 服务器管理服务

职责：MCP 服务器配置的 CRUD 操作
单一职责：只负责服务器配置的数据库持久化
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.mcp import McpServer
from app.repositories.mcp_server import McpServerRepository
from app.schemas.mcp import McpServerCreate, McpServerUpdate
from app.services.base import BaseService


class McpServerService(BaseService[McpServer]):
    """
    MCP 服务器管理服务

    职责:
    - MCP 服务器配置的 CRUD
    - 不涉及工具注册（由 ToolService 负责）

    设计原则：
    - 单一职责：只负责服务器配置管理
    - 高内聚：所有方法都与服务器配置相关
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
        创建 MCP 服务器

        Args:
            user_id: 用户 ID
            data: 创建数据

        Returns:
            创建的 MCP 服务器
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
                "connection_status": "disconnected",
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
        更新 MCP 服务器配置

        Args:
            server_id: 服务器 ID
            user_id: 用户 ID
            data: 更新数据

        Returns:
            更新后的 MCP 服务器
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
        删除 MCP 服务器 (硬删除)

        Args:
            server_id: 服务器 ID
            user_id: 用户 ID

        Returns:
            是否删除成功
        """
        server = await self.get_with_permission(server_id, user_id)

        # 硬删除：彻底移除记录，避免唯一约束被软删除的行占用
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
        获取 MCP 服务器

        Args:
            server_id: 服务器 ID
            user_id: 用户 ID

        Returns:
            MCP 服务器
        """
        return await self.get_with_permission(server_id, user_id)

    async def get_by_id(self, server_id: uuid.UUID) -> Optional[McpServer]:
        """
        根据 ID 获取服务器（无权限检查，内部使用）

        Args:
            server_id: 服务器 ID

        Returns:
            MCP 服务器或 None
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
        获取用户可访问的 MCP 服务器列表（用户级别）

        Args:
            user_id: 用户 ID
            enabled_only: 是否只返回启用的

        Returns:
            MCP 服务器列表
        """
        return await self.repo.find_for_user_scope(
            user_id=user_id,
            enabled_only=enabled_only,
        )

    async def list_all_enabled(self) -> List[McpServer]:
        """
        获取所有启用的服务器（用于启动加载）

        Returns:
            所有启用的 MCP 服务器
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
        切换启用状态

        Args:
            server_id: 服务器 ID
            user_id: 用户 ID
            enabled: 是否启用

        Returns:
            更新后的 MCP 服务器
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
        更新连接状态

        Args:
            server_id: 服务器 ID
            status: 连接状态
            error: 错误信息

        Returns:
            更新后的 MCP 服务器
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
        更新工具数量

        Args:
            server_id: 服务器 ID
            tool_count: 工具数量

        Returns:
            更新后的 MCP 服务器
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
        获取服务器并检查权限

        Args:
            server_id: 服务器 ID
            user_id: 用户 ID

        Returns:
            MCP 服务器

        Raises:
            NotFoundException: 服务器不存在或无权限
        """
        server = await self.repo.get(server_id)

        if not server or server.deleted_at:
            raise NotFoundException("MCP server not found")

        if server.user_id != user_id:
            raise NotFoundException("MCP server not found")  # Security: don't reveal existence

        return server

    def needs_resync(self, update_data: McpServerUpdate, server: McpServer) -> bool:
        """
        判断更新是否需要重新同步工具

        Args:
            update_data: 更新数据
            server: 当前服务器

        Returns:
            是否需要重新同步
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
        批量获取 MCP 服务器（用于工具解析）

        Args:
            server_ids: 服务器 ID 列表
            user_id: 可选的用户 ID（用于权限过滤）

        Returns:
            UUID -> McpServer 的映射字典
        """
        return await self.repo.get_by_ids(server_ids, user_id)
