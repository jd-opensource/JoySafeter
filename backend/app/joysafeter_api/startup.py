"""API service startup hooks."""

from __future__ import annotations

import os

from loguru import logger

from app.joysafeter_shared.cache.redis import RedisClient


async def run_api_startup() -> None:
    # v1 model-management and MCP tool registry are gone — see the v1 cleanup
    # pass that removed ``ModelCredential``/``ModelInstance``/``ModelUsageLog``
    # and the ``McpServer*`` services. The only startup work left here is
    # wiring the session broadcaster so SSE live events survive across the
    # request fleet. If a future feature needs additional one-shot init,
    # add a private helper here rather than reviving the old hooks.
    await _initialize_session_broadcaster()


async def _initialize_session_broadcaster() -> None:
    try:
        from app.joysafeter_orchestrator.lifespan import ensure_session_broadcaster
        from app.joysafeter_shared.config.settings import joysafeter_config

        ensure_session_broadcaster(
            redis_client=RedisClient.get_client(),
            instance_id=f"{joysafeter_config.instance_id}:api:{os.getpid()}",
        )
        logger.info("   ✓ Session broadcaster ready")
    except Exception as e:
        logger.warning(f"   ⚠️  Session broadcaster initialization failed: {e}")
        logger.warning("   SSE live events will be degraded until broadcaster is available")
