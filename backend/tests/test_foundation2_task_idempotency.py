"""Foundation 2 (effectively-once) — task submission idempotency.

Failure scenario: a client (or an HA API replica) retries a task submission.
Without an idempotency key this creates a *second* task — for a pentest platform
that means running the tools against the target twice (externally visible,
irreversible). One idempotency key must map to exactly one task.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService


@pytest_asyncio.fixture
async def agent_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"test-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_same_task(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    key = f"idem-{uuid.uuid4()}"

    first = await svc.create_task(agent_id=agent_id, prompt="scan target", idempotency_key=key)
    second = await svc.create_task(agent_id=agent_id, prompt="scan target", idempotency_key=key)

    assert first.id == second.id, "retry with same idempotency key must return the original task"

    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent_id)
    )
    assert total == 1, "exactly one task row must exist for a repeated idempotency key"


@pytest.mark.asyncio
async def test_concurrent_same_key_creates_one_task(postgres_url, db_session, agent_id):
    """Two HA API replicas submit the same idempotency key at the same instant.

    This is the real go-live guarantee: an app-level check-then-insert would
    race here, so the DB unique constraint + ON CONFLICT must be the arbiter.
    """
    import asyncio

    key = f"idem-concurrent-{uuid.uuid4()}"
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def submit() -> uuid.UUID:
        async with factory() as session:
            task = await JoySafeterTaskService(session).create_task(
                agent_id=agent_id, prompt="scan target", idempotency_key=key
            )
            return task.id

    try:
        first_id, second_id = await asyncio.gather(submit(), submit())
    finally:
        await engine.dispose()

    assert first_id == second_id, "concurrent submits with the same key must resolve to one task"

    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.idempotency_key == key)
    )
    assert total == 1, "a concurrent double-submit must create exactly one task"


@pytest.mark.asyncio
async def test_get_by_idempotency_key_hit_and_miss(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    key = f"idem-lookup-{uuid.uuid4()}"

    assert await svc.get_by_idempotency_key(key) is None, "unknown key must return None"

    created = await svc.create_task(agent_id=agent_id, prompt="scan target", idempotency_key=key)
    found = await svc.get_by_idempotency_key(key)
    assert found is not None and found.id == created.id, "known key must return the created task"
