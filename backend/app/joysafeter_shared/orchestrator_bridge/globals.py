"""Global singleton registry for API-owned session broadcasting."""

import logging

logger = logging.getLogger(__name__)

_session_broadcaster = None


def get_session_broadcaster():
    return _session_broadcaster


def ensure_session_broadcaster(redis_client=None, instance_id: str | None = None):
    """Ensure a lightweight SessionBroadcaster exists for API-only service roles.

    In split-service deployments the API process does not run the full
    orchestrator startup, but it still owns the SSE endpoint and must subscribe
    to Redis session events.
    """
    global _session_broadcaster
    if _session_broadcaster is None:
        from app.joysafeter_shared.config.settings import joysafeter_config

        from .session_broadcaster import SessionBroadcaster

        _session_broadcaster = SessionBroadcaster(
            redis_client=redis_client,
            instance_id=instance_id or joysafeter_config.instance_id,
        )
        logger.info("SessionBroadcaster initialized (via orchestrator_bridge)")
    return _session_broadcaster


def set_session_broadcaster(v):
    global _session_broadcaster
    _session_broadcaster = v
