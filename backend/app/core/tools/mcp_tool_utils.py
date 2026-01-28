"""
MCP Tool Utilities - 统一的 MCP 工具名称解析和验证工具函数

提供统一的工具函数用于：
1. 解析 MCP 工具名称（格式：server_name::tool_name）
2. 查找真实的 MCP server instance
3. 验证和获取 MCP 工具
"""

import uuid
from typing import Optional, Tuple

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools.tool import EnhancedTool
from app.core.tools.tool_registry import MCP_TOOL_KEY_SEPARATOR, get_global_registry
from app.models.mcp import McpServer
from app.services.mcp_server_service import McpServerService


def _assert_not_uuid(server_identifier: str, context: str = "") -> None:
    """
    断言 server_identifier 不是 UUID 格式

    如果 server_identifier 是 UUID 格式，则抛出 AssertionError。
    这确保我们始终使用服务器名称而不是 UUID。

    Args:
        server_identifier: 服务器标识符
        context: 上下文信息（用于错误消息）

    Raises:
        AssertionError: 如果 server_identifier 是 UUID 格式
    """
    if not server_identifier:
        return

    try:
        uuid.UUID(server_identifier)
        # 如果是有效的 UUID，抛出断言错误
        context_msg = f" in {context}" if context else ""
        raise AssertionError(
            f"Server identifier must be a server name, not UUID{context_msg}: {server_identifier}. "
            f"Please use the server name (e.g., 'my_server') instead of UUID."
        )
    except (ValueError, AttributeError, TypeError):
        # 不是 UUID 格式，通过检查
        pass


def parse_mcp_tool_name(tool_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 MCP 工具名称（格式：server_name::tool_name）

    Args:
        tool_name: 工具名称，可能是 "server_name::tool_name" 格式或普通工具名称

    Returns:
        (server_name, tool_name) 元组，如果不是 MCP 工具格式则返回 (None, None)

    Examples:
        >>> parse_mcp_tool_name("my_server::my_tool")
        ("my_server", "my_tool")
        >>> parse_mcp_tool_name("builtin_tool")
        (None, None)
    """
    if not tool_name or MCP_TOOL_KEY_SEPARATOR not in tool_name:
        return None, None

    parts = tool_name.split(MCP_TOOL_KEY_SEPARATOR, 1)
    if len(parts) != 2:
        return None, None

    server_name = parts[0].strip()
    actual_tool_name = parts[1].strip()

    if not server_name or not actual_tool_name:
        return None, None

    # 断言 server_name 不是 UUID 格式
    _assert_not_uuid(server_name, f"parsing tool '{tool_name}'")

    return server_name, actual_tool_name


async def resolve_mcp_server_instance(server_name: str, user_id: str, db: AsyncSession) -> Optional[McpServer]:
    """
    通过 server_name 查找真实的 MCP server instance

    Args:
        server_name: MCP 服务器名称（每个用户唯一，必须是名称，不能是 UUID）
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        McpServer 实例，如果不存在或已删除则返回 None

    Raises:
        AssertionError: 如果 server_name 是 UUID 格式
    """
    if not server_name or not user_id:
        logger.warning(
            f"[resolve_mcp_server_instance] Invalid parameters: server_name={server_name}, user_id={user_id}"
        )
        return None

    # 断言 server_name 不是 UUID 格式
    _assert_not_uuid(server_name, f"resolve_mcp_server_instance(user_id={user_id})")

    try:
        service = McpServerService(db)
        server = await service.repo.get_by_name(user_id, server_name)

        if not server:
            logger.warning(
                f"[resolve_mcp_server_instance] MCP server not found by name: "
                f"server_name={server_name}, user_id={user_id}"
            )
            return None

        if server.deleted_at:
            logger.debug(
                f"[resolve_mcp_server_instance] MCP server is deleted: server_name={server_name}, user_id={user_id}"
            )
            return None

        logger.debug(
            f"[resolve_mcp_server_instance] Found server: "
            f"server_name={server.name}, server_id={server.id}, user_id={user_id}"
        )
        return server

    except Exception as e:
        logger.error(f"[resolve_mcp_server_instance] Error resolving MCP server instance: {e}", exc_info=True)
        return None


async def validate_mcp_server_for_tool(server: McpServer, user_id: str) -> bool:
    """
    验证 MCP server instance 是否可用于工具执行

    Args:
        server: MCP 服务器实例
        user_id: 用户 ID

    Returns:
        True 如果服务器可用，False 否则
    """
    if not server:
        return False

    # 验证用户权限
    if server.user_id != user_id:
        logger.warning(f"[validate_mcp_server_for_tool] User {user_id} does not own server {server.name}")
        return False

    # 验证服务器已启用
    if not server.enabled:
        logger.warning(f"[validate_mcp_server_for_tool] Server {server.name} is disabled")
        return False

    return True


async def get_mcp_tool_with_instance(
    server_name: str, tool_name: str, user_id: str, db: AsyncSession
) -> Optional[EnhancedTool]:
    """
    获取 MCP 工具并验证 server instance

    完整的验证流程：
    1. 查找 MCP server instance（通过 server_name）
    2. 验证 server instance（权限、启用状态）
    3. 从 registry 获取工具（使用 server.name）

    Args:
        server_name: MCP 服务器名称（每个用户唯一）
        tool_name: 工具名称
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        EnhancedTool 实例，如果验证失败则返回 None
    """
    # 1. 查找 MCP server instance
    server = await resolve_mcp_server_instance(server_name, user_id, db)
    if not server:
        logger.warning(
            f"[get_mcp_tool_with_instance] MCP server not found: server_name={server_name}, user_id={user_id}"
        )
        return None

    # 2. 验证 server instance
    if not await validate_mcp_server_for_tool(server, user_id):
        logger.warning(
            f"[get_mcp_tool_with_instance] MCP server validation failed: server_name={server_name}, user_id={user_id}"
        )
        return None

    # 3. 从 registry 获取工具（使用 server.name）
    registry = get_global_registry()
    tool = registry.get_mcp_tool(server.name, tool_name)

    if not tool:
        logger.warning(
            f"[get_mcp_tool_with_instance] Tool not found in registry: server_name={server_name}, tool_name={tool_name}"
        )
        return None

    logger.debug(
        f"[get_mcp_tool_with_instance] Successfully retrieved tool: server_name={server_name}, tool_name={tool_name}"
    )

    return tool


async def resolve_mcp_tool_from_string(tool_id: str, user_id: str, db: AsyncSession) -> Optional[EnhancedTool]:
    """
    从字符串格式的工具 ID 解析并获取 MCP 工具（统一入口）

    支持格式：
    - "server_name::tool_name" - MCP 工具（必须使用服务器名称，不能使用 UUID）
    - 其他格式将被忽略（返回 None）

    Args:
        tool_id: 工具 ID 字符串，格式: "server_name::tool_name"
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        EnhancedTool 实例，如果不是 MCP 工具格式或验证失败则返回 None
    """
    server_name, tool_name = parse_mcp_tool_name(tool_id)
    if not server_name or not tool_name:
        return None

    return await get_mcp_tool_with_instance(server_name, tool_name, user_id, db)


async def resolve_mcp_tools_from_list(tool_ids: list[str], user_id: str, db: AsyncSession) -> list[EnhancedTool]:
    """
    批量解析并获取 MCP 工具列表（统一入口）

    Args:
        tool_ids: 工具 ID 列表，格式: ["server_name::tool_name", ...]
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        EnhancedTool 实例列表
    """
    tools = []
    for tool_id in tool_ids:
        tool = await resolve_mcp_tool_from_string(tool_id, user_id, db)
        if tool:
            tools.append(tool)
    return tools
