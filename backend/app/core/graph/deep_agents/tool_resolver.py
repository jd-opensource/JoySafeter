"""Tool resolver — resolves tool names to executable tool instances."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger


async def resolve_tools(
    tool_names: List[Any],
    user_id: Optional[str] = None,
) -> List[Any]:
    """Resolve tool names/configs to executable tool instances.

    Supports:
    - String tool names (looked up from registry or DB)
    - Dict tool configs (custom tools with parameters)
    - Already-instantiated tool objects (passed through)
    """
    if not tool_names:
        return []

    from app.core.agent.node_tools import resolve_tools_for_node

    try:
        resolved = await resolve_tools_for_node(tool_names, user_id=user_id)
        logger.info(f"[ToolResolver] Resolved {len(resolved)} tools from {len(tool_names)} names")
        return resolved
    except Exception as e:
        logger.warning(f"[ToolResolver] Tool resolution failed: {e}")
        return []
