import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_orchestrator.kernel.scheduler import TaskScheduler
from app.joysafeter_shared.utils.datetime import utc_now


class _NoopQueue:
    async def push_to_global(self, task_id):
        return None

    async def push_to_sandbox(self, sandbox_id, task_id):
        return None

    async def pop_from_global(self):
        return None


@pytest.mark.asyncio
async def test_scheduler_archived_agent_terminalizes_session(postgres_url, db_session, monkeypatch):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    agent = JoySafeterAgent(name=f"archived-scheduler-agent-{uuid.uuid4()}", archived_at=utc_now())
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="should not schedule",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    try:
        scheduler = TaskScheduler(_NoopQueue())
        await scheduler._scheduling_semaphore.acquire()
        await scheduler._schedule_task(task_id)
    finally:
        await engine.dispose()

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "session.status_idle",
            )
        )
    ).scalar_one()

    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
    assert session_row.status == "idle"
    assert session_row.stop_reason == {"type": "cancelled"}
    assert event.payload == {"task_id": str(task_id), "stop_reason": {"type": "cancelled"}}
