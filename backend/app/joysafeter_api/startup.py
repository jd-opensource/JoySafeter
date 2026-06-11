"""API service startup hooks."""

from __future__ import annotations

from loguru import logger

from app.joysafeter_shared.database import AsyncSessionLocal
from app.joysafeter_shared.cache.redis import RedisClient


async def run_api_startup() -> None:
    await _initialize_session_broadcaster()
    await _sync_model_providers()
    await _initialize_mcp_tools()


async def _initialize_session_broadcaster() -> None:
    try:
        from app.joysafeter_orchestrator.lifespan import ensure_session_broadcaster
        from app.joysafeter_shared.config.settings import joysafeter_config

        ensure_session_broadcaster(
            redis_client=RedisClient.get_client(),
            instance_id=joysafeter_config.instance_id,
        )
        logger.info("   ✓ Session broadcaster ready")
    except Exception as e:
        logger.warning(f"   ⚠️  Session broadcaster initialization failed: {e}")
        logger.warning("   SSE live events will be degraded until broadcaster is available")


async def _sync_model_providers() -> None:
    try:
        from app.joysafeter_domain.repositories.model_provider import ModelProviderRepository
        from app.joysafeter_api.services import ModelProviderService

        async with RedisClient.lock("init:model_providers", timeout=60, blocking_timeout=60):
            async with AsyncSessionLocal() as db:
                provider_repo = ModelProviderRepository(db)
                provider_count = await provider_repo.count()

                from app.joysafeter_shared.model.factory import get_factory

                factory_provider_count = len(get_factory().get_all_providers())
                if provider_count != factory_provider_count:
                    logger.info(
                        f"   Provider count mismatch (DB: {provider_count}, Factory: {factory_provider_count}), starting auto-sync..."
                    )
                provider_service = ModelProviderService(db)
                result = await provider_service.sync_all()
                if provider_count != factory_provider_count:
                    logger.info(f"   ✓ Auto-sync completed: {result['providers']} providers, {result['models']} models")
                    if result.get("errors"):
                        for error in result["errors"]:
                            logger.warning(f"   ⚠️  {error}")
                else:
                    logger.info(f"   ✓ Provider sync completed ({result['providers']} providers updated)")
    except Exception as e:
        logger.warning(f"   ⚠️  Auto-sync providers failed: {e}")
        logger.warning("   App will continue starting, you can manually call /api/v1/model-providers/sync later")


async def _initialize_mcp_tools() -> None:
    try:
        from app.joysafeter_api.services import initialize_mcp_tools_on_startup

        async with RedisClient.lock("init:mcp_tools", timeout=60, blocking_timeout=60):
            async with AsyncSessionLocal() as db:
                total_tools = await initialize_mcp_tools_on_startup(db)
                if total_tools > 0:
                    logger.info(f"   ✓ Loaded {total_tools} MCP tools to registry")
                else:
                    logger.info("   ✓ MCP tools initialization completed (no enabled servers)")
    except Exception as e:
        logger.warning(f"   ⚠️  MCP tools initialization failed: {e}")
        logger.warning("   App will continue starting, MCP tools will be loaded on first use")
