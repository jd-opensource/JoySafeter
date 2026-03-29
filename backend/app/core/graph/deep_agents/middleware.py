"""Middleware resolver — resolves memory middleware for agent nodes."""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger

from app.core.graph.deep_agents.model_resolver import ModelResolver


async def resolve_memory_middleware(
    enable_memory: bool,
    memory_model_name: Optional[str],
    memory_prompt: Optional[str],
    model_resolver: ModelResolver,
    user_id: Optional[str] = None,
    graph_id: Optional[str] = None,
) -> List[Any]:
    """Resolve memory middleware if enabled. Returns list of middleware instances."""
    if not enable_memory:
        return []

    try:
        from app.core.agent.memory.middleware import MemoryMiddleware

        # Resolve memory model (reuses the same ModelResolver)
        memory_model = await model_resolver.resolve(model_name=memory_model_name)
        if not memory_model:
            logger.warning("[MiddlewareResolver] Memory model resolution failed, skipping memory")
            return []

        middleware = MemoryMiddleware(
            model=memory_model,
            user_id=user_id,
            graph_id=graph_id,
            memory_prompt=memory_prompt,
        )
        logger.info("[MiddlewareResolver] Memory middleware created")
        return [middleware]

    except ImportError:
        logger.warning("[MiddlewareResolver] MemoryMiddleware not available")
        return []
    except Exception as e:
        logger.warning(f"[MiddlewareResolver] Memory middleware failed: {e}")
        return []
