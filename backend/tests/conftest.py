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
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from pytest import FixtureRequest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC = Path(sys.executable).with_name("alembic")

# ``Settings`` requires SECRET_KEY at import time (no default), and the module-level
# ``settings = Settings()`` runs during collection. Provide a deterministic test
# value so ``uv run pytest`` works without external secrets, matching how the other
# required env vars below are injected. A real value in the environment still wins.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local-and-ci-runs-only")
# CredentialCipher (vault/secret tests) requires a 32-byte AES key as 64 hex chars.
os.environ.setdefault(
    "JOYSAFETER_VAULT_ENCRYPTION_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

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
    external_url = os.environ.get("JOYSAFETER_TEST_DATABASE_URL")
    if external_url:
        url = make_url(external_url)
        os.environ["POSTGRES_HOST"] = url.host or "localhost"
        os.environ["POSTGRES_PORT"] = str(url.port or 5432)
        os.environ["POSTGRES_PORT_HOST"] = str(url.port or 5432)
        os.environ["POSTGRES_USER"] = url.username or "postgres"
        os.environ["POSTGRES_PASSWORD"] = url.password or "postgres"
        os.environ["POSTGRES_DB"] = (url.database or "joysafeter").lstrip("/")
        subprocess.run(
            [ALEMBIC, "upgrade", "head"],
            cwd=BACKEND_ROOT,
            check=True,
            env=os.environ.copy(),
        )
        from app.joysafeter_shared.config.settings import settings

        yield settings.database_url
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgres:15-alpine",
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
            [ALEMBIC, "upgrade", "head"],
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
async def _clean_tables(request: FixtureRequest) -> AsyncIterator[None]:
    """Isolate tests: truncate every table after each test.

    The Postgres container is session-scoped and the service commits, so without
    this rows leak between tests. TRUNCATE ... CASCADE resets all app tables.
    """
    if request.node.get_closest_marker("no_db"):
        yield
        return

    postgres_url = request.getfixturevalue("postgres_url")
    yield
    from app.joysafeter_shared.database import Base

    metadata_table_names = {table.name for table in Base.metadata.sorted_tables}
    if not metadata_table_names:
        return
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            existing_result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            )
            existing_table_names = metadata_table_names.intersection(existing_result.scalars())
            tables = ", ".join(f'"{name}"' for name in sorted(existing_table_names))
            if not tables:
                return
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_agent(db_session: AsyncSession):
    """Insert one agent (name="客服机器人", project_id="project-a") for name-resolution tests.

    ``joysafeter_agents.project_id`` carries a FK to ``joysafeter_organization_projects``,
    so an owning organization + project (id="project-a") are seeded first.
    """
    import uuid

    from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
    from app.joysafeter_domain.models.joysafeter_organization import Organization
    from app.joysafeter_domain.models.joysafeter_project import Project

    suffix = str(uuid.uuid4())
    organization = Organization(name=f"seeded-org-{suffix}", slug=f"seeded-org-{suffix}")
    db_session.add(organization)
    await db_session.flush()
    project = Project(
        id="project-a",
        org_id=organization.id,
        name=f"seeded-project-{suffix}",
        slug=f"seeded-project-{suffix}",
    )
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(name="客服机器人", project_id="project-a")
    db_session.add(agent)
    await db_session.commit()
    return agent
