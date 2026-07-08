"""Orchestrator bridge — shared code used by API/Worker around the Rust
orchestrator boundary.

In normal deployments the getter functions return ``None`` and callers fall back
to Redis-based communication.  The ``ensure_session_broadcaster`` helper is the
only one that actively initializes an object: the ``SessionBroadcaster`` used by
the API SSE endpoint.
"""

from .globals import (
    ensure_session_broadcaster,
    get_bridge_registry,
    get_envoy_manager,
    get_image_builder,
    get_memory_subscribers,
    get_redis_coordinator,
    get_sandbox_provider,
    get_sandbox_resolver,
    get_scheduler,
    get_session_broadcaster,
    set_bridge_registry,
    set_envoy_manager,
    set_image_builder,
    set_memory_subscribers,
    set_redis_coordinator,
    set_sandbox_provider,
    set_sandbox_resolver,
    set_scheduler,
    set_session_broadcaster,
)
from .image_builder import ImageBuilder
from .runtime_config import RuntimeConfig

__all__ = [
    # Getters
    "get_bridge_registry",
    "get_envoy_manager",
    "get_image_builder",
    "get_memory_subscribers",
    "get_redis_coordinator",
    "get_sandbox_provider",
    "get_sandbox_resolver",
    "get_scheduler",
    "get_session_broadcaster",
    "ensure_session_broadcaster",
    # Setters (for orchestrator startup)
    "set_bridge_registry",
    "set_envoy_manager",
    "set_image_builder",
    "set_memory_subscribers",
    "set_redis_coordinator",
    "set_sandbox_provider",
    "set_sandbox_resolver",
    "set_scheduler",
    "set_session_broadcaster",
    # Classes
    "ImageBuilder",
    "RuntimeConfig",
]
