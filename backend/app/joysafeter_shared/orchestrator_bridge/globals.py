"""Global singleton registry for orchestrator components.

API and Worker services use the getter functions to access orchestrator
internals (bridge registry, redis coordinator, etc.).  In Rust-orchestrator
mode these remain ``None`` and callers fall back to Redis-based communication.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global singletons — initialized to None; set by orchestrator startup
# ---------------------------------------------------------------------------

_scheduler = None
_session_broadcaster = None
_bridge_registry = None
_sandbox_resolver = None
_sandbox_provider = None
_envoy_manager = None
_memory_subscribers = None
_image_builder = None
_redis_coordinator = None
_event_bus = None
_event_buffer = None


# ---------------------------------------------------------------------------
# Getters (used by API / Worker)
# ---------------------------------------------------------------------------

def get_scheduler():
    return _scheduler


def get_session_broadcaster():
    return _session_broadcaster


def get_bridge_registry():
    return _bridge_registry


def get_sandbox_resolver():
    return _sandbox_resolver


def get_sandbox_provider():
    return _sandbox_provider


def get_envoy_manager():
    return _envoy_manager


def get_memory_subscribers():
    return _memory_subscribers


def get_image_builder():
    return _image_builder


def get_redis_coordinator():
    return _redis_coordinator


def get_event_bus():
    return _event_bus


def get_event_buffer():
    return _event_buffer


def ensure_session_broadcaster(redis_client=None, instance_id: str | None = None):
    """Ensure a lightweight SessionBroadcaster exists for API-only service roles.

    In split-service deployments the API process does not run the full
    orchestrator startup, but it still owns the SSE endpoint and must subscribe
    to Redis session events.  This initializes only the broadcaster without
    starting scheduler / sandbox / gRPC components.
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


# ---------------------------------------------------------------------------
# Setters (used by orchestrator startup to inject live instances)
# ---------------------------------------------------------------------------

def set_scheduler(v):
    global _scheduler
    _scheduler = v


def set_session_broadcaster(v):
    global _session_broadcaster
    _session_broadcaster = v


def set_bridge_registry(v):
    global _bridge_registry
    _bridge_registry = v


def set_sandbox_resolver(v):
    global _sandbox_resolver
    _sandbox_resolver = v


def set_sandbox_provider(v):
    global _sandbox_provider
    _sandbox_provider = v


def set_envoy_manager(v):
    global _envoy_manager
    _envoy_manager = v


def set_memory_subscribers(v):
    global _memory_subscribers
    _memory_subscribers = v


def set_image_builder(v):
    global _image_builder
    _image_builder = v


def set_redis_coordinator(v):
    global _redis_coordinator
    _redis_coordinator = v
