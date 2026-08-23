"""Shared startup/shutdown helpers for JoySafeter service roles."""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import text

from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.database import AsyncSessionLocal, close_db, engine
from app.joysafeter_shared.observation.otel.global_provider import init_global_provider
from app.joysafeter_shared.observation.otel.provider import init_global_processors
from app.joysafeter_shared.security.credential_cipher import CredentialCipher
from app.joysafeter_shared.security.credential_encryption_canary import (
    validate_credential_encryption_canaries,
)


def validate_credential_encryption_configuration() -> None:
    from app.joysafeter_shared.config.settings import joysafeter_config

    CredentialCipher(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    ).require_enabled()


def validate_llm_catalog_configuration() -> None:
    get_llm_catalog()


async def _check_db_connection() -> None:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select 1"))
        logger.info("   Database connection check: OK")
    except Exception as e:
        logger.opt(exception=True).error(f"   Database connection check failed: {e}")


async def validate_credential_encryption_database_state() -> None:
    from app.joysafeter_infrastructure.sensitive_material import (
        validate_credential_encryption_storage_coverage,
    )
    from app.joysafeter_shared.config.settings import joysafeter_config

    cipher = CredentialCipher(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    )
    cipher.require_enabled()
    async with AsyncSessionLocal() as db:
        await validate_credential_encryption_canaries(db, cipher)
        await validate_credential_encryption_storage_coverage(db, cipher)


async def _check_redis_connection() -> None:
    if not settings.redis_url:
        logger.info("   Redis connection check: Skipped (not configured)")
        return

    try:
        is_healthy = await RedisClient.health_check()
        if is_healthy:
            logger.info("   Redis connection check: OK")
        else:
            logger.error("   ⚠️  Redis connection check failed: Health check returned False")
    except Exception as e:
        logger.opt(exception=True).error(f"   Redis connection check failed: {e}")


async def _check_docker_availability() -> None:
    from app.joysafeter_shared.runtime.docker_check import is_docker_available

    docker_ok = await asyncio.to_thread(is_docker_available)
    if docker_ok:
        logger.info("   Docker connection check: OK")
    else:
        logger.warning(
            "   ⚠️  Docker is not available. Code execution sandboxes and "
            "skill preloading will be disabled until Docker Desktop is started."
        )


async def _run_common_startup() -> None:
    validate_llm_catalog_configuration()
    init_global_provider()
    init_global_processors()

    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"   Environment: {settings.environment}")
    logger.info(f"   Debug: {settings.debug}")
    logger.info(f"   Service role: {current_role().value}")

    if settings.environment == "production" and "localhost" in settings.frontend_url:
        logger.warning(
            "⚠️  WARNING: You are running in 'production' environment, but FRONTEND_URL "
            "contains 'localhost'. This will break email links, OAuth callbacks, "
            "and other frontend integrations! Please update FRONTEND_URL in your .env file."
        )

    if settings.redis_url:
        try:
            await RedisClient.init()
            if RedisClient.is_available():
                logger.info(f"   Redis connected (pool_size={settings.redis_pool_size})")
            else:
                logger.warning("   Redis unavailable after init; continuing in degraded mode")
        except Exception as e:
            logger.error(f"   ⚠️  Redis connection failed: {e}")
    else:
        logger.info("   Redis not configured (caching/rate-limiting disabled)")

    await _check_db_connection()
    await validate_credential_encryption_database_state()
    await _check_redis_connection()


async def _run_common_shutdown() -> None:
    try:
        await RedisClient.close()
    except Exception:
        logger.debug("Failed to close Redis client during shutdown", exc_info=True)

    try:
        from app.joysafeter_shared.observation.otel.global_provider import get_global_provider

        get_global_provider().shutdown()
        logger.info("   ✓ OTel TracerProvider shut down")
    except Exception:
        logger.debug("Failed to shut down TracerProvider during shutdown", exc_info=True)

    await close_db()
    logger.info("Application shutdown")
