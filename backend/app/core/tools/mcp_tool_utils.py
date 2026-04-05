"""
MCP Tool Utilities - Unified MCP tool name parsing and validation helpers.

Provide unified utility functions for:
1. Parsing MCP tool names (format: server_name::tool_name)
2. Resolving the actual MCP server instance
3. Validating and retrieving MCP tools
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
    """Assert that server_identifier is not a UUID.

    Raise AssertionError if server_identifier is a valid UUID,
    ensuring we always use server names rather than UUIDs.

    Args:
        server_identifier: Server identifier string.
        context: Context info for the error message.

    Raises:
        AssertionError: If server_identifier is a UUID.
    """
    if not server_identifier:
        return

    try:
        uuid.UUID(server_identifier)
        # valid UUID — raise assertion error
        context_msg = f" in {context}" if context else ""
        raise AssertionError(
            f"Server identifier must be a server name, not UUID{context_msg}: {server_identifier}. "
            f"Please use the server name (e.g., 'my_server') instead of UUID."
        )
    except (ValueError, AttributeError, TypeError):
        # not a UUID — passes the check
        pass


def parse_mcp_tool_name(tool_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse an MCP tool name (format: server_name::tool_name).

    Args:
        tool_name: Tool name, possibly in "server_name::tool_name" format.

    Returns:
        (server_name, tool_name) tuple; (None, None) if not in MCP format.

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

    _assert_not_uuid(server_name, f"parsing tool '{tool_name}'")

    return server_name, actual_tool_name


async def resolve_mcp_server_instance(server_name: str, user_id: str, db: AsyncSession) -> Optional[McpServer]:
    """Resolve the actual MCP server instance by server_name.

    Args:
        server_name: MCP server name (unique per user; must be a name, not a UUID).
        user_id: User ID.
        db: Database session.

    Returns:
        McpServer instance, or None if not found or deleted.

    Raises:
        AssertionError: If server_name is a UUID.
    """
    if not server_name or not user_id:
        logger.warning(
            f"[resolve_mcp_server_instance] Invalid parameters: server_name={server_name}, user_id={user_id}"
        )
        return None

    _assert_not_uuid(server_name, f"resolve_mcp_server_instance(user_id={user_id})")

    try:
        service = McpServerService(db)
        server = await service.repo.get_by_name(user_id, server_name)

        if not server:
            error_msg = f"MCP server not found by name: server_name={server_name}, user_id={user_id}"
            logger.error(f"[resolve_mcp_server_instance] {error_msg}")
            raise RuntimeError(f"MCP server '{server_name}' not found.")

        if server.deleted_at:
            error_msg = f"MCP server is deleted: server_name={server_name}, user_id={user_id}"
            logger.error(f"[resolve_mcp_server_instance] {error_msg}")
            raise RuntimeError(f"MCP server '{server_name}' has been deleted.")

        logger.debug(
            f"[resolve_mcp_server_instance] Found server: "
            f"server_name={server.name}, server_id={server.id}, user_id={user_id}"
        )
        return server

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[resolve_mcp_server_instance] Error resolving MCP server instance: {e}", exc_info=True)
        raise RuntimeError(f"Error resolving MCP server '{server_name}': {str(e)}")


async def validate_mcp_server_for_tool(server: McpServer, user_id: str) -> bool:
    """Validate that an MCP server instance is usable for tool execution.

    Args:
        server: MCP server instance.
        user_id: User ID.

    Returns:
        True if the server is usable.

    Raises:
        RuntimeError: If validation fails.
    """
    if not server:
        raise RuntimeError("MCP server instance is None.")

    # verify user ownership
    if server.user_id != user_id:
        error_msg = f"User {user_id} does not own server {server.name}"
        logger.error(f"[validate_mcp_server_for_tool] {error_msg}")
        raise RuntimeError(f"Permission denied: You do not own MCP server '{server.name}'.")

    # verify server is enabled
    if not server.enabled:
        error_msg = f"Server {server.name} is disabled"
        logger.warning(f"[validate_mcp_server_for_tool] {error_msg}")
        raise RuntimeError(f"MCP server '{server.name}' is disabled.")

    return True


async def get_mcp_tool_with_instance(
    server_name: str, tool_name: str, user_id: str, db: AsyncSession
) -> Optional[EnhancedTool]:
    """Retrieve an MCP tool after validating its server instance.

    Full validation flow:
    1. Resolve MCP server instance by server_name
    2. Validate server instance (ownership, enabled status)
    3. Look up tool in the registry using server.name

    Args:
        server_name: MCP server name (unique per user).
        tool_name: Tool name.
        user_id: User ID.
        db: Database session.

    Returns:
        EnhancedTool instance.

    Raises:
        RuntimeError: If any validation step fails.
    """
    # 1. resolve MCP server instance
    server = await resolve_mcp_server_instance(server_name, user_id, db)
    if not server:
        # resolve_mcp_server_instance now raises RuntimeError, so this branch might be unreachable
        # but kept for robustness if resolve_mcp_server_instance returns None
        raise RuntimeError(f"MCP server '{server_name}' not found.")

    # 2. validate server instance
    await validate_mcp_server_for_tool(server, user_id)

    # 3. look up tool in registry using server.name
    registry = get_global_registry()
    tool = registry.get_mcp_tool(server.name, tool_name)

    if not tool:
        error_msg = f"Tool not found in registry: server_name={server_name}, tool_name={tool_name}"
        logger.error(f"[get_mcp_tool_with_instance] {error_msg}")
        raise RuntimeError(f"MCP tool '{tool_name}' not found on server '{server_name}'.")

    logger.debug(
        f"[get_mcp_tool_with_instance] Successfully retrieved tool: server_name={server_name}, tool_name={tool_name}"
    )

    return tool


async def resolve_mcp_tool_from_string(tool_id: str, user_id: str, db: AsyncSession) -> Optional[EnhancedTool]:
    """Parse a string tool ID and retrieve the MCP tool (unified entry point).

    Supported formats:
    - "server_name::tool_name" — MCP tool (must use server name, not UUID)
    - Other formats are ignored (returns None)

    Args:
        tool_id: Tool ID string, format: "server_name::tool_name".
        user_id: User ID.
        db: Database session.

    Returns:
        EnhancedTool instance, or None if not in MCP format or validation fails.
    """
    server_name, tool_name = parse_mcp_tool_name(tool_id)
    if not server_name or not tool_name:
        return None

    return await get_mcp_tool_with_instance(server_name, tool_name, user_id, db)


async def resolve_mcp_tools_from_list(tool_ids: list[str], user_id: str, db: AsyncSession) -> list[EnhancedTool]:
    """Batch-resolve a list of MCP tool IDs (unified entry point).

    Args:
        tool_ids: Tool ID list, format: ["server_name::tool_name", ...].
        user_id: User ID.
        db: Database session.

    Returns:
        List of EnhancedTool instances.
    """
    tools = []
    for tool_id in tool_ids:
        tool = await resolve_mcp_tool_from_string(tool_id, user_id, db)
        if tool:
            tools.append(tool)
    return tools
