"""Tool resolver — resolves tool names to executable tool instances."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger


async def resolve_tools(
    tool_names: List[Any],
    user_id: Optional[str] = None,
    backend: Any = None,
) -> List[Any]:
    """Resolve tool names/configs to executable tool instances.

    Creates a minimal GraphNode-like object to satisfy resolve_tools_for_node's interface.
    """
    if not tool_names:
        return []

    from app.core.agent.node_tools import resolve_tools_for_node

    # resolve_tools_for_node expects a GraphNode with data.config.tools
    # Create a minimal shim
    class _NodeShim:
        def __init__(self, tools: list) -> None:
            self.id = "deep_agents_shim"
            self.data = {"config": {"tools": tools}}

    try:
        resolved = await resolve_tools_for_node(
            _NodeShim(tool_names),  # type: ignore[arg-type]
            user_id=user_id,
            backend=backend,
        )
        result = resolved or []
        logger.info(f"[ToolResolver] Resolved {len(result)} tools from {len(tool_names)} names")
        return result
    except Exception as e:
        logger.warning(f"[ToolResolver] Tool resolution failed: {e}")
        return []
