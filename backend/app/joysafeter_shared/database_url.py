"""Database URL construction that is safe to use during migrations."""

import os
import socket

from loguru import logger
from sqlalchemy.engine.url import make_url


def _is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def database_url_from_env() -> str:
    """Build the async PostgreSQL URL from the POSTGRES_* environment."""
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    postgres_db = os.getenv("POSTGRES_DB", "joysafeter")

    if postgres_host in ("localhost", "127.0.0.1", "::1"):
        postgres_port = os.getenv("POSTGRES_PORT_HOST") or os.getenv("POSTGRES_PORT", "5432")
    else:
        postgres_port = os.getenv("POSTGRES_PORT", "5432")

    database_url = (
        f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    )

    try:
        url = make_url(database_url)
        host = url.host
        port = url.port
        if host in ("localhost", "127.0.0.1", "::1") and port:
            if not _is_tcp_port_open(host, port) and port != 5432 and _is_tcp_port_open(host, 5432):
                url = url.set(port=5432)
                database_url = url.render_as_string(hide_password=False)
                logger.warning(f"Database connection to {host}:{port} failed, auto-switched to 5432")
    except Exception:
        pass

    return database_url


def database_url_sync_from_env() -> str:
    """Build the synchronous PostgreSQL URL used by Alembic."""
    return database_url_from_env().replace("+asyncpg", "")
