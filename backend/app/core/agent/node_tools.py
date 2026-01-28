"""
Node tools resolution.

Parses `GraphNode` tool configuration (persisted in DB) and resolves it into a
LangChain-compatible tools list for `create_agent(..., tools=[...])`.

Frontend stores tools under:
- node.data.config.tools = { builtin: string[], mcp: string[] }
  where mcp entries are in format `${server_name}::${toolName}`.
Backend also has a dedicated `GraphNode.tools` JSONB field; we support both.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger

# MCP tools are now loaded from ToolRegistry instead of direct connections
# Import default user ID constant
from app.core.constants import DEFAULT_USER_ID
from app.core.tools.tool import EnhancedTool, ToolMetadata, ToolSourceType
from app.models.graph import GraphNode


def _first_dict(*candidates: Any) -> Optional[dict]:
    for c in candidates:
        if isinstance(c, dict):
            return c
    return None


def extract_tools_config(node: GraphNode) -> Optional[dict]:
    """
    Extract tools config dict from a GraphNode.

    Preference order:
    1) node.data.config.tools (frontend canonical)
    2) node.tools (DB dedicated field)
    3) node.data.tools (legacy)
    """
    data = node.data or {}
    config = data.get("config", {}) if isinstance(data, dict) else {}
    tools_from_config = config.get("tools") if isinstance(config, dict) else None

    tools_dict = _first_dict(tools_from_config, node.tools, data.get("tools") if isinstance(data, dict) else None)
    if not tools_dict:
        return None
    return tools_dict


def _parse_mcp_ids(mcp_ids: Iterable[str]) -> Dict[str, Set[str]]:
    """解析 MCP 工具 ID (格式: server_name::tool_name)"""
    result: Dict[str, Set[str]] = {}

    for raw in mcp_ids:
        if not raw:
            continue

        # Split by "::" separator
        if "::" not in raw:
            logger.warning(
                f"[_parse_mcp_ids] Invalid format (missing '::'): '{raw}'. Expected format: 'server_name::tool_name'"
            )
            continue

        server_name, tool_name = raw.split("::", 1)
        server_name = (server_name or "").strip()
        tool_name = (tool_name or "").strip()

        if not server_name:
            logger.warning(f"[_parse_mcp_ids] Missing server name in: '{raw}'")
            continue

        if not tool_name:
            logger.warning(f"[_parse_mcp_ids] Missing tool name in: '{raw}'")
            continue

        result.setdefault(server_name, set()).add(tool_name)

    return result


def _alias_tool(*, name: str, description: str, callable_func: Any) -> EnhancedTool:
    """Create an EnhancedTool with a stable user-facing `name`."""
    return EnhancedTool.from_callable(  # type: ignore
        callable_func=callable_func,
        name=name,
        description=description,
        tool_metadata=ToolMetadata(source_type=ToolSourceType.BUILTIN, tags={"builtin"}, category="node"),
    )


def _resolve_builtin_tools(*, builtin_ids: List[str], root_dir: Path) -> List[Any]:
    """
    Resolve builtin tool IDs into LangChain tools.

    Current frontend IDs are mocked (`web_search`, `code_interpreter`), so we map them
    to concrete tool implementations:
    - web_search -> TavilyTools.web_search_using_tavily
    - code_interpreter -> PythonTools.run_python_code

    For tools registered in tool_registry (like tavily_search, think_tool),
    we first try to get them from the registry.
    """
    # Try to get tools from registry first
    from app.core.tools.tool_registry import get_global_registry

    registry = get_global_registry()

    # Lazy imports to avoid import-time failures when optional dependencies
    # (e.g. `tavily-python`) are not installed.
    from app.core.tools.buildin.file import FileTools
    from app.core.tools.buildin.python import PythonTools

    files = FileTools(base_dir=root_dir)
    python = PythonTools(base_dir=root_dir)

    tavily = None
    try:
        from app.core.tools.buildin.tavily import TavilyTools

        tavily = TavilyTools()
    except Exception as e:
        # Tavily is optional; only required if `web_search` is selected.
        logger.warning(f"[node_tools] TavilyTools not available: {type(e).__name__}: {e}")

    # Research tools - get from registry only
    research_tools = {}
    for tool_id in ["tavily_search", "think_tool"]:
        registry_tool = registry.get_tool(tool_id)
        if registry_tool:
            research_tools[tool_id] = registry_tool
            logger.debug(f"[node_tools] Found {tool_id} in registry")
        else:
            logger.warning(f"[node_tools] Tool '{tool_id}' not found in registry, skipping")

    # Canonical mapping for UI-friendly IDs -> tool implementations.
    aliases: Dict[str, Any] = {
        "web_search": _alias_tool(
            name="web_search",
            description="Search the web (Tavily).",
            callable_func=(
                tavily.web_search_using_tavily
                if tavily
                else (lambda *args, **kwargs: "Error: TavilyTools not installed")
            ),
        ),
        "code_interpreter": _alias_tool(
            name="code_interpreter",
            description="Execute Python code (dangerous; requires supervision).",
            callable_func=python.run_python_code,
        ),
        **research_tools,  # Add research tools to aliases
        # Some additional useful primitives (if UI sends them)
        "read_file": _alias_tool(
            name="read_file",
            description="Read a file under the per-user sandbox directory.",
            callable_func=files.read_file,
        ),
        "list_files": _alias_tool(
            name="list_files",
            description="List files under the per-user sandbox directory.",
            callable_func=files.list_files,
        ),
        "search_files": _alias_tool(
            name="search_files",
            description="Search files under the per-user sandbox directory by glob pattern.",
            callable_func=files.search_files,
        ),
        "save_file": _alias_tool(
            name="save_file",
            description="Save a file under the per-user sandbox directory.",
            callable_func=files.save_file,
        ),
    }

    resolved: List[Any] = []
    for tool_id in builtin_ids:
        if not tool_id:
            continue
        t = aliases.get(tool_id)
        if t is None:
            logger.warning(f"[node_tools] Unknown builtin tool id '{tool_id}', skipping")
            continue
        resolved.append(t)
    return resolved


def _safe_tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or "")


def _normalize_user_id(user_id: Any | None) -> str:
    """
    Normalize user_id to a string format.

    Converts UUID objects to strings, handles None by returning DEFAULT_USER_ID.
    Ensures all user_id values are strings (UUID format).

    Args:
        user_id: User ID (can be UUID object, string, or None)

    Returns:
        Normalized user_id as string (UUID format)
    """
    if user_id is None:
        return DEFAULT_USER_ID

    # Convert UUID object to string if needed
    if isinstance(user_id, uuid.UUID):
        return str(user_id)

    # Already a string
    if isinstance(user_id, str):
        return user_id

    # Fallback: convert to string
    return str(user_id)


async def _validate_mcp_servers(
    server_names: Iterable[str],
    user_id: str | None = None,
) -> Set[str]:
    """
    Validate MCP server names exist, are enabled, and belong to the user.

    Args:
        server_names: Iterable of server names to validate
        user_id: User ID for looking up MCP servers (normalized to string)

    Returns:
        Set of valid server names (enabled and accessible)
    """
    # Normalize user_id
    normalized_user_id = _normalize_user_id(user_id)

    valid_servers: Set[str] = set()

    if not server_names:
        return valid_servers

    try:
        from app.core.database import async_session_factory
        from app.services.mcp_server_service import McpServerService

        async with async_session_factory() as db:
            service = McpServerService(db)

            # Validate each server name
            for server_name in server_names:
                try:
                    server = await service.repo.get_by_name(normalized_user_id, server_name)

                    if not server:
                        logger.warning(
                            f"[_validate_mcp_servers] MCP server not found by name: '{server_name}' "
                            f"(user_id={normalized_user_id})"
                        )
                        continue

                    if not server.enabled:
                        logger.warning(
                            f"[_validate_mcp_servers] MCP server '{server_name}' is disabled "
                            f"(user_id={normalized_user_id})"
                        )
                        continue

                    valid_servers.add(server_name)
                    logger.debug(f"[_validate_mcp_servers] Validated server name '{server_name}'")
                except Exception as e:
                    logger.error(
                        f"[_validate_mcp_servers] Error validating server name '{server_name}': {e}", exc_info=True
                    )
                    continue

        return valid_servers

    except Exception as e:
        logger.error(f"[_validate_mcp_servers] Error creating database session: {e}", exc_info=True)
        return valid_servers


async def resolve_tools_for_node(node: GraphNode, *, user_id: str | None = None) -> Optional[List[Any]]:
    """
    Resolve tools list for a node.

    Process flow:
    1. Extract tools config from node
    2. Parse builtin tools → resolve to tool objects
    3. Parse MCP tools → resolve server names → get tools
    4. Return combined tool list

    MCP server identification: server name (unique per user)

    Args:
        node: GraphNode to resolve tools for
        user_id: User ID (normalized to string UUID format)

    Returns:
        - None: means "no explicit tools config" (caller may use defaults)
        - [] / [..]: explicit tool list
    """
    # Normalize user_id
    normalized_user_id = _normalize_user_id(user_id)

    logger.debug(f"[resolve_tools_for_node] Starting resolution for node_id={node.id}, user_id={normalized_user_id}")

    # Step 1: Extract tools config
    cfg = extract_tools_config(node)
    if cfg is None:
        logger.debug(f"[resolve_tools_for_node] No tools config found for node_id={node.id}")
        return None

    logger.debug(f"[resolve_tools_for_node] Tools config: {cfg}")

    builtin_ids = cfg.get("builtin") if isinstance(cfg, dict) else None
    mcp_ids = cfg.get("mcp") if isinstance(cfg, dict) else None

    builtin_ids_list = list(builtin_ids) if isinstance(builtin_ids, list) else []
    mcp_ids_list = list(mcp_ids) if isinstance(mcp_ids, list) else []

    logger.debug(f"[resolve_tools_for_node] Parsed config: builtin_ids={builtin_ids_list}, mcp_ids={mcp_ids_list}")

    root_dir = Path(f"/tmp/{normalized_user_id}")
    tools: List[Any] = []

    # Step 2: Resolve builtin tools
    if builtin_ids_list:
        logger.debug(f"[resolve_tools_for_node] Resolving {len(builtin_ids_list)} builtin tools")
        builtin_tools = _resolve_builtin_tools(builtin_ids=builtin_ids_list, root_dir=root_dir)
        logger.debug(f"[resolve_tools_for_node] Resolved {len(builtin_tools)} builtin tools")
        tools.extend(builtin_tools)

    # Step 3: Resolve MCP tools from Registry with instance validation
    if mcp_ids_list:
        logger.debug(f"[resolve_tools_for_node] Resolving {len(mcp_ids_list)} MCP tools")

        from app.core.database import async_session_factory
        from app.core.tools.mcp_tool_utils import resolve_mcp_tools_from_list

        async with async_session_factory() as db:
            mcp_tools = await resolve_mcp_tools_from_list(mcp_ids_list, normalized_user_id, db)

        logger.debug(f"[resolve_tools_for_node] Retrieved {len(mcp_tools)} MCP tools")
        tools.extend(mcp_tools)

    logger.debug(
        f"[resolve_tools_for_node] Final resolution for node_id={node.id} | "
        f"builtin_selected={len(builtin_ids_list)} | mcp_selected={len(mcp_ids_list)} | "
        f"tools_resolved={len(tools)}"
    )

    # Final check: ensure no ToolMetadata objects in the list
    from app.core.tools.tool import ToolMetadata

    for i, tool in enumerate(tools):
        if isinstance(tool, ToolMetadata):
            logger.error(
                f"[resolve_tools_for_node] ERROR: ToolMetadata object found at index {i} "
                f"in tools list! This should not happen. metadata: {tool}"
            )

    return tools
