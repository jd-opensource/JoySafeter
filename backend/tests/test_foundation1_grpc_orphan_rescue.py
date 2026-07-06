import asyncio
import uuid

import pytest
from grpc import aio as grpc_aio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
from app.joysafeter_orchestrator.grpc.server import AgentBridgeServicer
from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridge, SandboxBridgeRegistry


class _FakeQueue:
    def __init__(self):
        self.pushed: list[uuid.UUID] = []
        self.drained: list[uuid.UUID] = []

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        self.pushed.append(task_id)

    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None:
        self.drained.append(sandbox_id)


class _EOFContext:
    async def read(self):
        return grpc_aio.EOF


class _FakeEventBuffer:
    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_grpc_orphan_rescue_does_not_requeue_exhausted_task(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-orphan-agent-{agent_id}")
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        retry_count=2,
        max_retries=2,
    )
    db_session.add_all([agent, task])
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    queue = _FakeQueue()
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=queue,
    )

    try:
        await servicer._rescue_orphaned_tasks(sandbox_id)
    finally:
        await engine.dispose()

    assert queue.pushed == []

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.FAILED.value
    assert row.error == "Runner reconnected without active task"


@pytest.mark.asyncio
async def test_grpc_cleanup_requeues_scheduling_task_after_failover(postgres_url, db_session, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-cleanup-agent-{agent_id}")
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        sandbox_id=sandbox_id,
        retry_count=0,
        max_retries=2,
    )
    db_session.add_all([agent, task])
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr(TaskController, "compute_retry_delay", staticmethod(lambda _retry_count, _task_id: 0.0))

    queue = _FakeQueue()
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=queue,
    )

    try:
        await servicer._execute_sandbox_cleanup(sandbox_id, None, [], is_error=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        await engine.dispose()

    assert queue.drained == [sandbox_id]
    assert queue.pushed == [task_id]

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.PENDING.value
    assert row.retry_count == 1
    assert row.sandbox_id is None


@pytest.mark.asyncio
async def test_grpc_cleanup_fails_exhausted_scheduling_task(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-cleanup-exhausted-agent-{agent_id}")
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        sandbox_id=sandbox_id,
        retry_count=2,
        max_retries=2,
    )
    db_session.add_all([agent, task])
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    queue = _FakeQueue()
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=queue,
    )

    try:
        await servicer._execute_sandbox_cleanup(sandbox_id, None, [], is_error=True)
    finally:
        await engine.dispose()

    assert queue.drained == [sandbox_id]
    assert queue.pushed == []

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.FAILED.value
    assert row.error == f"Sandbox {sandbox_id} cleaned up before task started"


@pytest.mark.asyncio
async def test_grpc_cleanup_marks_rescheduling_when_session_has_pending_retry(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-cleanup-pending-session-agent-{agent_id}")
    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add_all([agent, session])
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
        chat_session_id=session.id,
        retry_count=1,
        max_retries=2,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    queue = _FakeQueue()
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=queue,
    )

    try:
        await servicer._execute_sandbox_cleanup(sandbox_id, session_id, [], is_error=True)
    finally:
        await engine.dispose()

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.status == "rescheduling"
    event = (
        await db_session.execute(select(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id == session_id))
    ).scalar_one()
    assert event.event_type == "session.status_rescheduling"
    assert event.payload == {"stop_reason": {"type": "sandbox_failed"}}


@pytest.mark.asyncio
async def test_grpc_cleanup_does_not_idle_session_while_active_task_remains(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-cleanup-active-session-agent-{agent_id}")
    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add_all([agent, session])
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        chat_session_id=session.id,
        retry_count=0,
        max_retries=2,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    queue = _FakeQueue()
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=queue,
    )

    try:
        await servicer._execute_sandbox_cleanup(sandbox_id, session_id, [], is_error=True)
    finally:
        await engine.dispose()

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.status == "running"
    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    assert events == []


@pytest.mark.asyncio
async def test_reconnect_active_task_restores_owner_epoch_for_failover(postgres_url, db_session, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    owner_epoch = 42
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-reconnect-agent-{agent_id}")
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=owner_epoch,
    )
    db_session.add_all([agent, task])
    await db_session.commit()
    await db_session.refresh(task)

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    calls = []

    async def fake_failover(task_id, reason, expected_epoch=None):
        calls.append((task_id, reason, expected_epoch))
        return None

    monkeypatch.setattr(TaskController, "failover_or_fail_task", staticmethod(fake_failover))

    bridge = SandboxBridge(sandbox_id, "ext-reconnect")
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )

    try:
        await servicer._handle_reconnect_active_task(
            bridge,
            sandbox_id,
            str(task.id),
            _EOFContext(),
            stream_cancel=asyncio.Event(),
            failover_pending_tasks=[],
        )
    finally:
        await engine.dispose()

    assert bridge.current_owner_epoch == owner_epoch
    assert calls == [(task.id, "Sandbox disconnected after reconnect", owner_epoch)]


@pytest.mark.asyncio
async def test_run_single_task_dispatch_failure_failover_is_epoch_fenced(postgres_url, db_session, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    owner_epoch = 77
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-dispatch-agent-{agent_id}")
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=owner_epoch,
    )
    db_session.add_all([agent, task])
    await db_session.commit()
    await db_session.refresh(task)

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    async def fail_build_harness_input(*_args, **_kwargs):
        raise RuntimeError("build failed")

    monkeypatch.setattr(
        "app.joysafeter_orchestrator.kernel.harness_input_builder.build_harness_input",
        fail_build_harness_input,
    )

    calls = []

    async def fake_failover(task_id, reason, expected_epoch=None):
        calls.append((task_id, reason, expected_epoch))
        return None

    monkeypatch.setattr(TaskController, "failover_or_fail_task", staticmethod(fake_failover))

    bridge = SandboxBridge(sandbox_id, "ext-dispatch")
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )

    try:
        result = await servicer._run_single_task(
            bridge,
            sandbox_id,
            _EOFContext(),
            task.id,
            owner_epoch,
            stream_cancel=asyncio.Event(),
            failover_pending_tasks=[],
        )
    finally:
        await engine.dispose()

    assert result == (True, False, True, False)
    assert bridge.current_owner_epoch == owner_epoch
    assert calls == [(task.id, "build failed", owner_epoch)]


@pytest.mark.asyncio
async def test_handle_result_cas_conflict_has_no_side_effects(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-result-agent-{agent_id}")
    session = JoySafeterSession(id=session_id, agent_id=agent_id, status="running")
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-result",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=2,
    )
    db_session.add_all([agent, session, sandbox, task])
    await db_session.commit()
    await db_session.refresh(task)
    await db_session.refresh(session)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    bridge = SandboxBridge(sandbox_id, "ext-result")
    bridge.current_owner_epoch = 1
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )
    result = joysafeter_pb2.RunnerHarnessResult(
        status="completed",
        output="stale output",
        usage=joysafeter_pb2.TokenUsage(input_tokens=3, output_tokens=5),
        duration_ms=10,
    )

    try:
        accepted = await servicer._handle_result(bridge, sandbox_id, task_id, session_id, result)
    finally:
        await engine.dispose()

    assert accepted is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    sess = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    sbx = (await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value
    assert row.output == ""
    assert row.usage is None
    assert sess.status == "running"
    assert sess.usage["input_tokens"] == 0
    assert sbx.status == "running"


@pytest.mark.asyncio
async def test_handle_reconnect_result_cas_conflict_has_no_side_effects(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-reconnect-result-agent-{agent_id}")
    session = JoySafeterSession(id=session_id, agent_id=agent_id, status="running")
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-reconnect-result",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=9,
    )
    db_session.add_all([agent, session, sandbox, task])
    await db_session.commit()
    await db_session.refresh(task)
    await db_session.refresh(session)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    bridge = SandboxBridge(sandbox_id, "ext-reconnect-result")
    bridge.current_owner_epoch = 8
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )
    result = joysafeter_pb2.RunnerHarnessResult(
        status="completed",
        output="stale reconnect output",
        usage=joysafeter_pb2.TokenUsage(input_tokens=7, output_tokens=11),
        duration_ms=10,
    )

    try:
        accepted = await servicer._handle_reconnect_result(
            bridge,
            sandbox_id,
            task_id,
            session_id,
            result,
            coordinator=None,
        )
    finally:
        await engine.dispose()

    assert accepted is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    sess = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    sbx = (await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value
    assert row.output == ""
    assert row.usage is None
    assert sess.status == "running"
    assert sess.usage["input_tokens"] == 0
    assert sbx.status == "running"


@pytest.mark.asyncio
async def test_handle_result_non_terminal_status_is_failed(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    session_id = uuid.uuid4()
    owner_epoch = 31
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-result-nonterminal-agent-{agent_id}")
    session = JoySafeterSession(id=session_id, agent_id=agent_id, status="running")
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-result-nonterminal",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=owner_epoch,
    )
    db_session.add_all([agent, session, sandbox, task])
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    bridge = SandboxBridge(sandbox_id, "ext-result-nonterminal")
    bridge.current_owner_epoch = owner_epoch
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )
    result = joysafeter_pb2.RunnerHarnessResult(status="running", output="partial")

    try:
        accepted = await servicer._handle_result(bridge, sandbox_id, task_id, session_id, result)
    finally:
        await engine.dispose()

    assert accepted is True
    assert bridge.last_result_status == JoySafeterTaskStatus.FAILED
    assert bridge.last_result_error == "Runner returned non-terminal result status: running"

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    sess = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.FAILED.value
    assert row.error == "Runner returned non-terminal result status: running"
    assert sess.status == "idle"
    assert sess.stop_reason == {"type": "error", "message": "Runner returned non-terminal result status: running"}


@pytest.mark.asyncio
async def test_handle_result_persists_output_and_usage_before_terminal(postgres_url, db_session, monkeypatch):
    agent_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    owner_epoch = 41
    agent = JoySafeterAgent(id=agent_id, name=f"grpc-result-persist-agent-{agent_id}")
    sandbox = JoySafeterSandbox(
        id=sandbox_id,
        external_id="ext-result-persist",
        provider="docker",
        status="running",
        image="joysafeter/test",
    )
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sandbox_id,
        owner_epoch=owner_epoch,
    )
    db_session.add_all([agent, sandbox, task])
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    bridge = SandboxBridge(sandbox_id, "ext-result-persist")
    bridge.current_owner_epoch = owner_epoch
    servicer = AgentBridgeServicer(
        bridge_registry=SandboxBridgeRegistry(),
        event_buffer=_FakeEventBuffer(),
        queue=_FakeQueue(),
    )
    result = joysafeter_pb2.RunnerHarnessResult(
        status="completed",
        output="final report",
        usage=joysafeter_pb2.TokenUsage(input_tokens=13, output_tokens=17),
        duration_ms=123,
    )

    try:
        accepted = await servicer._handle_result(bridge, sandbox_id, task_id, None, result)
    finally:
        await engine.dispose()

    assert accepted is True
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.COMPLETED.value
    assert row.output == "final report"
    assert row.usage == {
        "input_tokens": 13,
        "output_tokens": 17,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
