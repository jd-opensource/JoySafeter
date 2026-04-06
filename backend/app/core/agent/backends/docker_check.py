"""Docker daemon availability check and shared client factory.

Centralizes all Docker client creation so that DOCKER_HOST, timeout,
and availability caching are handled in one place.  Every module that
needs a Docker client should call ``get_docker_client()`` instead of
``docker.from_env()`` directly.
"""

import json
import os
import pathlib
import time
from typing import Optional, Tuple

from loguru import logger

# ---------------------------------------------------------------------------
# Availability cache
# ---------------------------------------------------------------------------

_cache: Optional[Tuple[bool, float]] = None
_CACHE_TTL_SECONDS = 30.0


def is_docker_available(ttl: float = _CACHE_TTL_SECONDS) -> bool:
    """Check if the Docker daemon is reachable (cached)."""
    global _cache

    now = time.monotonic()
    if _cache is not None:
        cached_result, checked_at = _cache
        if (now - checked_at) < ttl:
            return cached_result

    result = _ping_docker()
    _cache = (result, now)
    return result


def _ping_docker() -> bool:
    try:
        client = get_docker_client(timeout=5)
        client.ping()
        return True
    except Exception as e:
        logger.debug(f"Docker daemon not reachable: {type(e).__name__}: {e}")
        return False


def reset_cache() -> None:
    """Reset the availability cache (for testing or after Docker starts)."""
    global _cache
    _cache = None


# ---------------------------------------------------------------------------
# Shared client factory
# ---------------------------------------------------------------------------

# Pin API version to skip the auto-detection GET /version round-trip.
# 1.41 = Docker Engine 20.10 (Dec 2020), safe minimum for any modern install.
_DEFAULT_API_VERSION = "1.41"


def get_docker_client(*, timeout: float = 10):
    """Create a Docker client that reads DOCKER_HOST from the environment.

    Supports Docker Desktop, Colima, Orbstack, remote daemons, and any
    setup that sets the ``DOCKER_HOST`` environment variable or uses
    Docker contexts.

    When ``DOCKER_HOST`` is not set, falls back to the active Docker
    context (``~/.docker/config.json`` → ``contexts/meta/``).  This is
    necessary because ``docker.from_env()`` only checks ``DOCKER_HOST``
    and the default socket ``/var/run/docker.sock``, but Colima and
    other runtimes place their socket elsewhere and register it via
    Docker contexts instead.

    Args:
        timeout: HTTP request timeout in seconds.

    Returns:
        ``docker.DockerClient`` instance.

    Raises:
        docker.errors.DockerException on connection failure.
    """
    import docker

    _ensure_docker_host()
    return docker.from_env(timeout=timeout, version=_DEFAULT_API_VERSION)


_docker_host_resolved = False


def _ensure_docker_host() -> None:
    """Set ``DOCKER_HOST`` from Docker context if not already set.

    Called once.  After this, every ``docker.from_env()`` — including
    those inside third-party libraries like ``pydantic_ai_backends`` —
    will connect to the correct socket.
    """
    global _docker_host_resolved
    if _docker_host_resolved:
        return
    _docker_host_resolved = True

    if os.environ.get("DOCKER_HOST"):
        return

    context_host = _resolve_docker_context_host()
    if context_host:
        os.environ["DOCKER_HOST"] = context_host
        logger.info(f"Set DOCKER_HOST from Docker context: {context_host}")


def _resolve_docker_context_host() -> Optional[str]:
    """Read the Docker host endpoint from the active Docker context.

    Returns the ``Host`` string (e.g. ``unix:///...``) or ``None`` if
    the context cannot be determined or is ``default`` (which uses the
    standard socket that ``docker.from_env()`` already tries).
    """
    try:
        docker_dir = pathlib.Path(os.environ.get("DOCKER_CONFIG", pathlib.Path.home() / ".docker"))
        config_file = docker_dir / "config.json"
        if not config_file.exists():
            return None

        config = json.loads(config_file.read_text())
        context_name = config.get("currentContext", "default")
        if context_name == "default":
            return None

        # Walk the contexts/meta directory to find the matching context
        meta_dir = docker_dir / "contexts" / "meta"
        if not meta_dir.is_dir():
            return None

        for ctx_dir in meta_dir.iterdir():
            meta_file = ctx_dir / "meta.json"
            if not meta_file.exists():
                continue
            meta = json.loads(meta_file.read_text())
            if meta.get("Name") == context_name:
                host = meta.get("Endpoints", {}).get("docker", {}).get("Host")
                if host:
                    logger.debug(f"Resolved Docker host from context '{context_name}': {host}")
                    return host

    except Exception as e:
        logger.debug(f"Failed to resolve Docker context host: {e}")

    return None
