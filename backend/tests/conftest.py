"""Shared pytest fixtures for JoySafeter integration tests.

All four resilience foundations rely on Postgres-specific behavior (advisory
locks, ``ON CONFLICT``, JSONB, concurrent races), so tests run against a real
ephemeral Postgres started via testcontainers — never sqlite.

``settings.database_url`` resolves the ``POSTGRES_*`` env vars via ``os.getenv``
at access time, so the container's connection params are injected into the
environment before any app engine is built, and the alembic subprocess inherits
them to migrate the fresh database.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# testcontainers talks to Docker via docker-py, which defaults to the socket at
# /var/run/docker.sock. On colima / Docker Desktop the real socket lives
# elsewhere, so derive it from the active docker context when DOCKER_HOST is
# unset, and disable ryuk (its socket-mount reaper is unreliable on those setups).
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
if not os.environ.get("DOCKER_HOST"):
    try:
        _host = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if _host:
            os.environ["DOCKER_HOST"] = _host
    except Exception:
        pass


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start one ephemeral Postgres for the whole test session, migrate it, and
    yield the async SQLAlchemy URL bound to it."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgres:16-alpine",
        username="postgres",
        password="postgres",
        dbname="joysafeter",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        os.environ["POSTGRES_HOST"] = "127.0.0.1" if host in ("localhost", "127.0.0.1", "") else host
        os.environ["POSTGRES_PORT"] = str(port)
        os.environ["POSTGRES_PORT_HOST"] = str(port)
        os.environ["POSTGRES_USER"] = "postgres"
        os.environ["POSTGRES_PASSWORD"] = "postgres"
        os.environ["POSTGRES_DB"] = "joysafeter"

        # Apply the real migration chain — this also validates new migrations.
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            check=True,
            env=os.environ.copy(),
        )

        # Build the async URL exactly the way the app does, from the env just set.
        from app.joysafeter_shared.config.settings import settings

        yield settings.database_url


@pytest_asyncio.fixture
async def db_session(postgres_url: str) -> AsyncIterator[AsyncSession]:
    """A fresh AsyncSession bound to the ephemeral Postgres.

    Uses NullPool so each test gets clean connections and the engine can be
    disposed without leaking pooled connections into the next test.
    """
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(postgres_url) -> AsyncIterator[None]:
    """Isolate tests: truncate every table after each test.

    The Postgres container is session-scoped and the service commits, so without
    this rows leak between tests. TRUNCATE ... CASCADE resets all app tables.
    """
    yield
    from app.joysafeter_shared.database import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if not tables:
        return
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()
