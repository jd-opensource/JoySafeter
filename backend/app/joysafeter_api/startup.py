"""API service startup hooks."""

from __future__ import annotations

import os

from loguru import logger

from app.joysafeter_identity_federation.bootstrap import initialize_identity_federation
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru


async def run_api_startup() -> None:
    initialize_identity_federation()

    from app.joysafeter_api.api.v1.agent_identity_capture import (
        validate_agent_identity_configuration,
    )

    validate_agent_identity_configuration()
    await _initialize_session_broadcaster()


async def _initialize_session_broadcaster() -> None:
    try:
        from app.joysafeter_shared.config.settings import joysafeter_config
        from app.joysafeter_shared.orchestrator_bridge import ensure_session_broadcaster

        ensure_session_broadcaster(
            redis_client=RedisClient.get_client(),
            instance_id=f"{joysafeter_config.instance_id}:api:{os.getpid()}",
        )
        logger.info("   ✓ Session broadcaster ready")
    except Exception as e:
        log_boundary_failure_loguru(
            logger,
            boundary="api_startup",
            code="API_SESSION_BROADCASTER_INIT_FAILED",
            message="Session broadcaster initialization failed",
            operation="initialize_session_broadcaster",
            error=e,
            data={"service": "api"},
        )
        logger.warning("   SSE live events will be degraded until broadcaster is available")
