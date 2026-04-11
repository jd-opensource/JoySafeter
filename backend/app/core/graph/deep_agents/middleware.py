"""Middleware resolver — resolves memory middleware for agent nodes."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger

from app.core.graph.deep_agents import format_node_ctx
from app.core.graph.deep_agents.model_resolver import ModelResolver


async def resolve_memory_middleware(
    enable_memory: bool,
    memory_model_name: Optional[str],
    memory_prompt: Optional[str],
    model_resolver: ModelResolver,
    user_id: Optional[str] = None,
    graph_id: Optional[str] = None,
    *,
    node_label: Optional[str] = None,
    graph_name: Optional[str] = None,
) -> List[Any]:
    """Resolve memory middleware if enabled. Returns list of middleware instances."""
    if not enable_memory:
        return []

    ctx = format_node_ctx(node_label, graph_name)

    try:
        from app.core.agent.memory.middleware import MemoryMiddleware

        memory_model = await model_resolver.resolve(
            model_name=memory_model_name,
            node_label=node_label,
            graph_name=graph_name,
        )
        if not memory_model:
            logger.warning(f"[MiddlewareResolver] Memory model resolution returned None for {ctx}, skipping memory")
            return []

        middleware = MemoryMiddleware(
            model=memory_model,
            user_id=user_id,
            graph_id=graph_id,
            memory_prompt=memory_prompt,
        )
        logger.info(f"[MiddlewareResolver] Memory middleware created for {ctx}")
        return [middleware]

    except ImportError:
        logger.warning(f"[MiddlewareResolver] MemoryMiddleware not available (requested by {ctx})")
        return []
    except Exception as e:
        logger.warning(f"[MiddlewareResolver] Memory middleware failed for {ctx}: {e}")
        return []
