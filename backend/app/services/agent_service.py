"""
Agent service utilities.

- Resolve selected tools for an Agent (AgentToolMap -> LangChain tools)
"""

from typing import Any, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools.buildin import time_tools
from app.core.tools.tool_registry import get_global_registry

# AgentToolMap may not exist in models, using type: ignore
try:
    from app.models import AgentToolMap  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    AgentToolMap = None  # type: ignore[assignment, misc]


async def resolve_tools_for_agent(db: AsyncSession, agent_id: int, user_id: Optional[str] = None) -> List[Any]:
    """
    Resolve the list of LangChain Tool objects for a given agent.

    Supports:
      - Builtin tools (currently time_tools)
      - MCP tools (from ToolRegistry, format: server_name::tool_name)
    """
    if AgentToolMap is None:
        logger.warning("AgentToolMap model not available")
        return []
    result = await db.execute(select(AgentToolMap).where(AgentToolMap.agent_id == agent_id))  # type: ignore[misc]
    rows: list[Any] = list(result.scalars().all())

    tools: list[Any] = []
    if not rows:
        return tools

    # Get global registry for MCP tools
    registry = get_global_registry()

    # Builtin tool registry (name -> callable Tool)
    builtin_registry: dict[str, Any] = {
        getattr(time_tools, name).__name__: getattr(time_tools, name)
        for name in getattr(time_tools, "__all__", [])
        if hasattr(time_tools, name)
    }

    # Validate MCP servers if we have MCP tools
    mcp_tool_ids = [row.tool_name for row in rows if row.source == "mcp"]
    valid_servers: set[str] = set()

    if mcp_tool_ids and user_id:
        # Parse server names from MCP tool IDs (format: server_name::tool_name)
        server_names = set()
        for tool_id in mcp_tool_ids:
            if "::" in tool_id:
                server_name = tool_id.split("::", 1)[0].strip()
                if server_name:
                    server_names.add(server_name)

        # Validate servers exist and are enabled
        if server_names:
            from app.core.agent.node_tools import _validate_mcp_servers

            valid_servers = await _validate_mcp_servers(server_names, user_id=user_id)
            logger.debug(
                f"[resolve_tools_for_agent] Validated {len(valid_servers)}/{len(server_names)} "
                f"MCP servers for agent_id={agent_id}"
            )

    for row in rows:
        try:
            if row.source == "builtin":
                tool_obj = builtin_registry.get(row.tool_name)
                if tool_obj is None:
                    logger.warning(f"Builtin tool '{row.tool_name}' not found in registry")
                    continue
                tools.append(tool_obj)
            elif row.source == "mcp":
                from app.core.tools.mcp_tool_utils import resolve_mcp_tool_from_string

                if user_id:
                    # 使用实例验证获取工具
                    tool = await resolve_mcp_tool_from_string(row.tool_name, user_id, db)
                else:
                    # 没有 user_id，直接从 registry 获取（不验证）
                    from app.core.tools.mcp_tool_utils import parse_mcp_tool_name

                    server_name, tool_name = parse_mcp_tool_name(row.tool_name)
                    if server_name and tool_name:
                        tool = registry.get_mcp_tool(server_name, tool_name)
                    else:
                        tool = None

                if tool:
                    tools.append(tool)
                else:
                    logger.warning(f"MCP tool '{row.tool_name}' not found or not accessible for agent_id={agent_id}")
            else:
                logger.warning(f"Unknown tool source '{row.source}' for tool '{row.tool_name}', skipping")
        except Exception as e:
            logger.warning(f"Failed to resolve tool '{row.tool_name}': {e}")

    logger.debug(f"Resolved {len(tools)} tools for agent_id={agent_id}")
    return tools
