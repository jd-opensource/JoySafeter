import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.utils.datetime import utc_now


class _FakeQueue:
    def __init__(self):
        self.pushed: list[uuid.UUID] = []

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        self.pushed.append(task_id)


async def _agent(db_session) -> uuid.UUID:
    agent_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"startup-recovery-agent-{agent_id}")
    db_session.add(agent)
    await db_session.commit()
    return agent_id


async def _recover(postgres_url, monkeypatch, queue: _FakeQueue) -> None:
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_redis_coordinator", lambda: None)
    try:
        await TaskController(queue).recover_on_startup()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_startup_recovery_requeues_scheduling_task_after_reset(postgres_url, db_session, monkeypatch):
    agent_id = await _agent(db_session)
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        retry_count=0,
        max_retries=2,
        sandbox_id=uuid.uuid4(),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    queue = _FakeQueue()
    await _recover(postgres_url, monkeypatch, queue)

    assert queue.pushed == [task_id]

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.PENDING.value
    assert row.retry_count == 1
    assert row.sandbox_id is None


@pytest.mark.asyncio
async def test_startup_recovery_fails_exhausted_scheduling_task(postgres_url, db_session, monkeypatch):
    agent_id = await _agent(db_session)
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        retry_count=2,
        max_retries=2,
        sandbox_id=uuid.uuid4(),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    queue = _FakeQueue()
    await _recover(postgres_url, monkeypatch, queue)

    assert queue.pushed == []

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.FAILED.value
    assert row.error == "Retries exhausted while recovering scheduling task on startup"


@pytest.mark.asyncio
async def test_startup_recovery_does_not_terminate_rescheduling_session_with_active_task(
    postgres_url, db_session, monkeypatch
):
    agent_id = await _agent(db_session)
    session = JoySafeterSession(agent_id=agent_id, status="rescheduling")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    await db_session.execute(
        sa_update(JoySafeterSession)
        .where(JoySafeterSession.id == session_id)
        .values(updated_at=utc_now() - timedelta(minutes=10))
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="retry turn",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    queue = _FakeQueue()
    await _recover(postgres_url, monkeypatch, queue)

    assert queue.pushed == [task_id]

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    assert session_row.status == "rescheduling"
    assert session_row.archived_at is None
    assert events == []
