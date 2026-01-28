"""
Tool Service - 统一工具管理服务

职责：
- 工具注册/注销（同步到 ToolRegistry）
- 工具查询（从 ToolRegistry 读取）
- 协调 MCP 服务器与工具同步

设计原则：
- 门面模式 (Facade)：提供统一的工具管理入口
- 组合优于继承：组合 McpServerService 和 McpClientService
- 单一职责：专注于工具管理，MCP 服务器 CRUD 委托给 McpServerService
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException
from app.core.tools.tool import EnhancedTool, ToolFilter, ToolSourceType
from app.core.tools.tool_registry import ToolRegistry, get_global_registry
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
    统一工具管理服务 (Facade)

    职责:
    - 协调 MCP 服务器管理与工具注册
    - 工具查询
    - 工具同步

    组合的服务:
    - McpServerService: MCP 服务器 CRUD
    - McpClientService: MCP 连接和工具获取
    - ToolRegistry: 工具注册中心
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
        """获取全局工具注册中心"""
        return self._registry

    @property
    def server_service(self) -> McpServerService:
        """获取 MCP 服务器服务"""
        return self._server_service

    # ==================== MCP Server Operations (Delegate) ====================

    async def create_mcp_server(
        self,
        user_id: str,
        data: McpServerCreate,
    ) -> McpServer:
        """
        创建 MCP 服务器并同步工具
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
        更新 MCP 服务器并同步工具到 registry

        处理逻辑：
        1. 名称变更：先注销旧名称工具，更新后注册新名称工具
        2. 状态变更：enabled→disabled 注销工具，disabled→enabled 同步工具
        3. 配置变更：如果连接配置改变，重新同步工具
        """
        # 获取当前服务器状态
        server = await self._server_service.get(server_id, user_id)
        old_name = server.name
        was_enabled = server.enabled

        # 检测变更类型
        name_changed = data.name is not None and data.name != server.name
        needs_resync = self._server_service.needs_resync(data, server)

        # 处理名称变更：先注销旧名称的工具
        if name_changed and was_enabled:
            await self._unregister_server_tools_by_name(old_name, user_id)

        # 执行更新
        server = await self._server_service.update(server_id, user_id, data)
        will_be_enabled = server.enabled

        # 处理工具同步逻辑
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
        删除 MCP 服务器并注销工具
        """
        server = await self._server_service.get(server_id, user_id)
        await self._unregister_server_tools(server)
        return await self._server_service.delete(server_id, user_id)

    async def get_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> McpServer:
        """获取 MCP 服务器"""
        return await self._server_service.get(server_id, user_id)

    async def list_mcp_servers(
        self,
        user_id: str,
        enabled_only: bool = False,
    ) -> List[McpServer]:
        """
        获取 MCP 服务器列表（用户级别）

        Args:
            user_id: 用户 ID
            enabled_only: 是否只返回启用的
        """
        return await self._server_service.list(user_id, enabled_only)

    async def toggle_mcp_server(
        self,
        server_id: uuid.UUID,
        user_id: str,
        enabled: bool,
    ) -> McpServer:
        """
        切换 MCP 服务器启用状态
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
        测试 MCP 服务器连接
        """
        server = await self._server_service.get(server_id, user_id)
        config = McpClientService.config_from_server(server)

        result = await self._mcp_client.test_connection(config, server)

        # Update server status
        if result.success:
            await self._server_service.update_connection_status(server_id, "connected")
        else:
            await self._server_service.update_connection_status(server_id, "error", result.error)

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
        刷新 MCP 服务器工具
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
        同步用户所有启用的 MCP 服务器工具（用户级别）

        Args:
            user_id: 用户 ID
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
        获取用户可用的工具列表（用户级别）

        Args:
            user_id: 用户 ID
            tool_type: 工具类型过滤
            category: 类别过滤
        """
        filter_config = self._build_filter(tool_type, category)

        tools = self._registry.get_tools_for_scope(
            user_id=user_id,
            workspace_id=None,  # 用户级别，无 workspace
            filter_config=filter_config,
            include_builtin=True,
        )

        return [self._tool_to_info(t) for t in tools]

    def get_builtin_tools(self) -> List[ToolInfo]:
        """获取所有内置工具"""
        tools = self._registry.get_tools(ToolFilter(source_types={ToolSourceType.BUILTIN}))
        return [self._tool_to_info(t) for t in tools]

    def get_tool_by_key(self, tool_key: str) -> Optional[ToolInfo]:
        """通过工具键获取工具信息"""
        tool = self._registry.get_tool(tool_key)
        return self._tool_to_info(tool) if tool else None

    def get_mcp_tool(self, server_name: str, tool_name: str) -> Optional[ToolInfo]:
        """获取 MCP 工具"""
        tool = self._registry.get_mcp_tool(server_name, tool_name)
        return self._tool_to_info(tool) if tool else None

    async def get_server_tools(
        self,
        server_id: uuid.UUID,
        user_id: str,
    ) -> List[ToolInfo]:
        """
        获取 MCP 服务器的工具列表

        先验证权限，再从 Registry 获取工具
        """
        # 验证权限
        server = await self._server_service.get(server_id, user_id)

        # 从 Registry 获取该服务器的工具
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
        处理更新后的工具同步逻辑

        Args:
            server: 更新后的服务器对象
            was_enabled: 更新前的启用状态
            will_be_enabled: 更新后的启用状态
            name_changed: 是否发生了名称变更
            needs_resync: 是否需要重新同步（配置变更）
        """
        # 情况1: 从 enabled 变为 disabled → 注销工具
        if not will_be_enabled and was_enabled:
            if not name_changed:  # 名称未变，使用新名称注销
                await self._unregister_server_tools(server)
            # 如果名称已变，旧名称的工具已在更新前注销

        # 情况2: 保持或变为 enabled → 根据条件同步工具
        elif will_be_enabled:
            should_sync = (
                needs_resync  # 配置改变需要重新同步
                or name_changed  # 名称改变需要注册新名称工具
                or not was_enabled  # 从 disabled 变为 enabled 需要同步
            )
            if should_sync:
                await self._sync_server_tools_safe(server)

    async def _sync_server_tools_safe(self, server: McpServer) -> None:
        """安全地同步服务器工具（捕获异常）"""
        try:
            await self._sync_server_tools(server)
        except Exception as e:
            logger.warning(f"Failed to sync tools for server {server.name}: {e}")

    async def _sync_server_tools(self, server: McpServer) -> List[ToolInfo]:
        """同步服务器工具到 Registry"""
        config = McpClientService.config_from_server(server)

        try:
            result = await self._mcp_client.connect_and_fetch_tools(config, server)

            if not result.success:
                await self._server_service.update_connection_status(server.id, "error", result.error)
                raise Exception(result.error)

            # Unregister old tools
            await self._unregister_server_tools(server)

            # Register new tools (user-level only)
            registered = self._registry.register_mcp_tools(
                mcp_server_name=server.name,
                tools=result.tools,
                owner_user_id=server.user_id,
                owner_workspace_id=None,  # 用户级别，无 workspace
                category="mcp",
            )

            # Update server stats
            await self._server_service.update_tool_count(server.id, len(registered))
            await self._server_service.update_connection_status(server.id, "connected")

            return [self._tool_to_info(t) for t in registered]

        except Exception as e:
            await self._server_service.update_connection_status(server.id, "error", str(e))
            raise

    # ==================== Private Helpers: Registry Operations ====================

    async def _unregister_server_tools(self, server: McpServer) -> int:
        """
        从 Registry 注销服务器的所有工具，并关闭对应的 Toolkit

        Args:
            server: MCP 服务器对象

        Returns:
            注销的工具数量
        """
        count = self._registry.unregister_mcp_server_tools(server.name)
        if count > 0:
            logger.info(f"Unregistered {count} tools from server: {server.name}")

        # 关闭对应的 Toolkit
        from app.services.mcp_toolkit_manager import get_toolkit_manager

        toolkit_manager = get_toolkit_manager()
        try:
            await toolkit_manager.close_toolkit(server.name, server.user_id)
        except Exception as e:
            logger.warning(f"Failed to close toolkit for server {server.name}: {e}")

        return count

    async def _unregister_server_tools_by_name(self, server_name: str, user_id: str) -> int:
        """
        根据服务器名称注销工具（用于名称变更场景），并关闭对应的 Toolkit

        Args:
            server_name: 服务器名称
            user_id: 用户 ID

        Returns:
            注销的工具数量
        """
        count = self._registry.unregister_mcp_server_tools(server_name)
        if count > 0:
            logger.info(f"Unregistered {count} tools from server: {server_name}")

        # 关闭对应的 Toolkit
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
        """构建工具过滤器"""
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
        转换 EnhancedTool 为 ToolInfo

        Args:
            tool: EnhancedTool 实例

        Returns:
            ToolInfo 对象
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
            owner_workspace_id=None,  # 用户级别，不再使用 workspace
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
    应用启动时加载所有启用的 MCP 服务器工具到全局 registry

    流程：
    1. 查询所有启用的 MCP 服务器
    2. 连接到每个服务器并获取工具列表（带重试机制）
    3. 将工具注册到全局 ToolRegistry
    4. 更新服务器的连接状态和工具数量

    Args:
        db: 数据库会话
        max_retries: 每个服务器连接失败时的最大重试次数
        retry_delay: 重试延迟（秒），使用指数退避
        allow_partial_failure: 如果为 True，单个服务器失败不会影响其他服务器

    Returns:
        加载的工具总数
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
                        owner_workspace_id=None,  # 用户级别，无 workspace
                        category="mcp",
                    )

                    await server_service.update_tool_count(server.id, len(registered))
                    await server_service.update_connection_status(server.id, "connected")

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
                        await server_service.update_connection_status(server.id, "error", result.error)
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
                    await server_service.update_connection_status(server.id, "error", str(e))
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
