import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridge, SandboxBridgeRegistry
from app.joysafeter_orchestrator.kernel.task_runner import TaskRunner, persist_task_scoped_session_status_event


class _FailingAdapter:
    async def start(self, _harness_input):
        raise RuntimeError("adapter failed")


class _ExistingSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc_info):
        return False


@pytest.mark.asyncio
async def test_runner_requeues_first_retry_when_failover_returns_zero(postgres_url, db_session, monkeypatch):
    """The first failover returns retry_count=0; runner must still requeue it."""
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    sandbox_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    owner_epoch = 11

    agent = JoySafeterAgent(
        id=agent_id,
        name=f"runner-retry-agent-{uuid.uuid4()}",
        engine_kind="claude",
        tools=[],
        mcp_configs=[],
        skills=[],
    )
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-runner-retry",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        retry_count=0,
        max_retries=2,
        owner_epoch=owner_epoch,
    )
    db_session.add_all([agent, sandbox, task])
    await db_session.commit()
    await db_session.refresh(task)

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    async def fake_build_harness_input(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(
        "app.joysafeter_orchestrator.kernel.harness_input_builder.build_harness_input",
        fake_build_harness_input,
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.retry.compute_retry_delay",
        lambda _retry_count, _task_id: 0.0,
    )

    failover_calls = []

    async def fake_failover(task_id, reason, expected_epoch=None):
        failover_calls.append((task_id, reason, expected_epoch))
        return 0

    monkeypatch.setattr(TaskController, "failover_or_fail_task", staticmethod(fake_failover))

    bridge = SandboxBridge(sandbox_id, "ext-runner-retry")
    runner = TaskRunner(
        bridge,
        queue=object(),
        adapter=_FailingAdapter(),
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=object(),
    )

    requeued = []

    async def fake_delayed_requeue(task_id, delay):
        requeued.append((task_id, delay))

    monkeypatch.setattr(runner, "_delayed_requeue", fake_delayed_requeue)

    try:
        await runner._execute_task(task.id, owner_epoch)
        await asyncio.sleep(0)
    finally:
        await engine.dispose()

    assert failover_calls == [(task.id, "adapter failed", owner_epoch)]
    assert requeued == [(task.id, 0.0)]


@pytest.mark.asyncio
async def test_runner_system_status_events_are_task_scoped_session_events(db_session, monkeypatch):
    sandbox_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    agent = JoySafeterAgent(
        id=agent_id,
        name=f"runner-status-agent-{uuid.uuid4()}",
        engine_kind="claude",
        tools=[],
        mcp_configs=[],
        skills=[],
    )
    session = JoySafeterSession(agent_id=agent_id, status="idle")
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-runner-status",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    db_session.add_all([agent, session, sandbox])
    await db_session.flush()
    await db_session.refresh(session)
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        chat_session_id=session.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    session_id = session.id
    task_id = task.id

    monkeypatch.setattr(
        "app.joysafeter_shared.database.AsyncSessionLocal",
        lambda: _ExistingSessionContext(db_session),
    )
    running_event = await persist_task_scoped_session_status_event(
        session_id=session_id,
        task_id=task_id,
        event_type="session.status_running",
        payload={},
    )
    idle_event = await persist_task_scoped_session_status_event(
        session_id=session_id,
        task_id=task_id,
        event_type="session.status_idle",
        payload={"stop_reason": {"type": "end_turn"}},
    )

    assert running_event is not None
    assert idle_event is not None

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == session_id)
                .order_by(JoySafeterSessionEvent.seq.asc())
            )
        )
        .scalars()
        .all()
    )

    assert session_row.status == "idle"
    assert [(event.event_type, event.payload) for event in events] == [
        ("session.status_running", {"task_id": str(task_id)}),
        ("session.status_idle", {"stop_reason": {"type": "end_turn"}, "task_id": str(task_id)}),
    ]
