"""Tool resolver — resolves tool names to executable tool instances."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger

from app.core.graph.deep_agents import format_node_ctx


async def resolve_tools(
    tool_names: List[Any],
    user_id: Optional[str] = None,
    backend: Any = None,
    *,
    node_label: Optional[str] = None,
    graph_name: Optional[str] = None,
) -> List[Any]:
    """Resolve tool names/configs to executable tool instances."""
    if not tool_names:
        return []

    from app.core.agent.node_tools import resolve_tools_for_node

    class _NodeShim:
        def __init__(self, tools: list) -> None:
            self.id = "deep_agents_shim"
            self.data = {"config": {"tools": tools}}

    ctx = format_node_ctx(node_label, graph_name)

    try:
        resolved = await resolve_tools_for_node(
            _NodeShim(tool_names),  # type: ignore[arg-type]
            user_id=user_id,
            backend=backend,
        )
        result = resolved or []
        logger.info(f"[ToolResolver] Resolved {len(result)} tools from {len(tool_names)} names for {ctx}")
        return result
    except Exception as e:
        logger.warning(f"[ToolResolver] Tool resolution failed for {ctx}: {e}")
        return []
