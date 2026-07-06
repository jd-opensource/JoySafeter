"""Foundation 1 (fencing) — owner_epoch fencing token.

The lease reclaim closes the ~2h hang, but leaves a residual race: instance A
takes task T to 'running', then STALLS (GC pause / partition) without crashing.
Its lease lapses, the watchdog requeues T, and T re-runs to 'running' under
instance B. Then zombie A wakes and makes a stale mutating write to T —
corrupting a task B now owns.

Each →RUNNING claim stamps a globally-monotonic ``owner_epoch`` (a Postgres
SEQUENCE). Every mutating write for a running task is conditioned on the epoch
it was granted; the zombie holds a stale epoch (a reclaim→re-run bumped it), so
its write matches zero rows and is dropped instead of corrupting the row.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine
from app.joysafeter_shared.common.app_errors import ConflictError


@pytest_asyncio.fixture
async def agent_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"fence-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


async def _scheduling_task(db_session, agent_id: uuid.UUID, sandbox_id: uuid.UUID) -> uuid.UUID:
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        sandbox_id=sandbox_id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task.id


@pytest.mark.asyncio
async def test_claim_returns_monotonic_epoch(db_session, agent_id):
    """Each →RUNNING claim stamps a fresh, strictly increasing fencing token."""
    sm = JoySafeterTaskStateMachine(db_session)
    sb1, sb2 = uuid.uuid4(), uuid.uuid4()
    t1 = await _scheduling_task(db_session, agent_id, sb1)
    t2 = await _scheduling_task(db_session, agent_id, sb2)

    claimed1 = await sm.claim_next_sandbox_task_for_running(sb1)
    claimed2 = await sm.claim_next_sandbox_task_for_running(sb2)

    assert claimed1 is not None and claimed1[0] == t1
    assert claimed2 is not None and claimed2[0] == t2
    assert claimed2[1] > claimed1[1], "epoch must be strictly monotonic across claims"

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == t1))).scalar_one()
    assert row.owner_epoch == claimed1[1], "the returned epoch must be the stamped one"


@pytest.mark.asyncio
async def test_stale_epoch_terminal_write_is_rejected(db_session, agent_id):
    """A zombie holding the pre-reclaim epoch cannot terminal-write a task that
    has since been reclaimed and re-run (epoch advanced)."""
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)

    claimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert claimed is not None
    stale_epoch = claimed[1]

    # Simulate reclaim → re-run: retry back to pending, re-schedule, re-claim (new epoch).
    await sm.retry(task_id)
    await db_session.execute(
        sa_update(JoySafeterTask)
        .where(JoySafeterTask.id == task_id)
        .values(status=JoySafeterTaskStatus.SCHEDULING.value, sandbox_id=sb)
    )
    await db_session.commit()
    reclaimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert reclaimed is not None and reclaimed[1] > stale_epoch

    # Zombie A (stale epoch) tries to mark it FAILED — must be rejected.
    ok = await sm.fail_with_error(task_id, "zombie write", JoySafeterTaskStatus.FAILED, expected_epoch=stale_epoch)
    assert ok is False, "the stale-epoch terminal write must be rejected"

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value, "task must still be running under the new owner"
    assert row.error is None, "the zombie's error must not have been written"


@pytest.mark.asyncio
async def test_current_epoch_terminal_write_succeeds(db_session, agent_id):
    """The legitimate current owner (matching epoch) can terminal-write."""
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    claimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert claimed is not None
    epoch = claimed[1]

    ok = await sm.transition_to(task_id, JoySafeterTaskStatus.COMPLETED, expected_epoch=epoch)
    assert ok is True

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_output_write_is_epoch_fenced(db_session, agent_id):
    """update_task_output honors the fencing epoch: a stale writer is a no-op,
    the current owner writes through."""
    sm = JoySafeterTaskStateMachine(db_session)
    svc = JoySafeterTaskService(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    claimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert claimed is not None
    epoch = claimed[1]

    wrote_stale = await svc.update_task_output(task_id, "zombie output", expected_epoch=epoch - 1)
    assert wrote_stale is False, "a stale-epoch output write must be a no-op"

    wrote_current = await svc.update_task_output(task_id, "real output", expected_epoch=epoch)
    assert wrote_current is True

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.output == "real output", "only the current owner's output persists"


@pytest.mark.asyncio
async def test_no_expected_epoch_preserves_unconditional_write(db_session, agent_id):
    """expected_epoch=None keeps the pre-fencing behavior for callers that don't
    hold a grant (e.g. pre-RUNNING scheduler/watchdog paths)."""
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    await sm.claim_next_sandbox_task_for_running(sb)

    ok = await sm.fail_with_error(task_id, "watchdog failure", JoySafeterTaskStatus.FAILED)
    assert ok is True, "with no epoch supplied the terminal write is unconditional (status-guarded only)"


@pytest.mark.asyncio
async def test_task_scoped_idle_does_not_override_other_active_task(db_session, agent_id):
    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    old_task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="old turn",
        status=JoySafeterTaskStatus.COMPLETED.value,
    )
    new_task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="new turn",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add_all([old_task, new_task])
    await db_session.commit()
    await db_session.refresh(old_task)

    updated = await SessionService(db_session).update_session_status_for_task_event(
        session_id,
        "idle",
        old_task.id,
        stop_reason={"type": "end_turn"},
    )

    assert updated is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    assert row.status == "running"
    assert row.stop_reason is None


@pytest.mark.asyncio
async def test_task_scoped_running_ignores_terminal_task(db_session, agent_id):
    session = JoySafeterSession(agent_id=agent_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="finished turn",
        status=JoySafeterTaskStatus.COMPLETED.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    updated = await SessionService(db_session).update_session_status_for_task_event(
        session_id,
        "running",
        task.id,
    )

    assert updated is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    assert row.status == "idle"


@pytest.mark.asyncio
async def test_task_scoped_running_does_not_override_other_active_task(db_session, agent_id):
    session = JoySafeterSession(
        agent_id=agent_id,
        status="idle",
        stop_reason={"type": "requires_action", "event_ids": ["evt_current"]},
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    old_task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="old turn",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    current_task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="current turn",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add_all([old_task, current_task])
    await db_session.commit()
    await db_session.refresh(old_task)

    updated = await SessionService(db_session).update_session_status_for_task_event(
        session_id,
        "running",
        old_task.id,
    )

    assert updated is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    assert row.status == "idle"
    assert row.stop_reason == {"type": "requires_action", "event_ids": ["evt_current"]}


@pytest.mark.asyncio
async def test_current_task_running_event_persists_when_session_already_running(
    postgres_url, db_session, agent_id, monkeypatch
):
    from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
    from app.joysafeter_orchestrator.events.session_state import SessionStateSubscriber

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="current turn",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    try:
        await SessionStateSubscriber().handle(
            JoySafeterEventEnvelope(
                session_id=session_id,
                event_type="session.status_running",
                payload={},
                task_id=task_id,
                is_status_change=True,
            )
        )
    finally:
        await engine.dispose()

    db_session.expire_all()
    event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "session.status_running",
            )
        )
    ).scalar_one()
    assert event.payload == {"task_id": str(task_id)}


@pytest.mark.asyncio
async def test_retry_clears_owner_epoch(db_session, agent_id):
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    await sm.claim_next_sandbox_task_for_running(sb)

    assert await sm.retry(task_id) is True
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.owner_epoch is None, "retry must clear the fencing token alongside owner/lease"


@pytest.mark.asyncio
async def test_retry_with_expected_epoch_is_single_use(db_session, agent_id):
    """The retry transition itself must be epoch-CAS fenced, not only the
    caller's pre-read. Otherwise two failure handlers holding the same epoch can
    both retry and consume two attempts."""
    svc = JoySafeterTaskService(db_session)
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    claimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert claimed is not None
    epoch = claimed[1]

    assert await svc.increment_retry(task_id, expected_epoch=epoch) is True
    assert await svc.increment_retry(task_id, expected_epoch=epoch) is False

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.PENDING.value
    assert row.retry_count == 1, "the same owner epoch must not consume retry twice"
    assert row.owner_epoch is None


@pytest.mark.asyncio
async def test_cancel_is_atomic_against_concurrent_terminal_write(postgres_url, db_session, agent_id):
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="cancel race",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as other_db:
            await other_db.execute(
                sa_update(JoySafeterTask)
                .where(JoySafeterTask.id == task_id)
                .values(status=JoySafeterTaskStatus.COMPLETED.value)
            )
            await other_db.commit()

        with pytest.raises(ValueError):
            await JoySafeterTaskStateMachine(db_session).cancel(task_id)
    finally:
        await engine.dispose()

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_failover_with_stale_epoch_is_dropped(postgres_url, db_session, agent_id, monkeypatch):
    """End-to-end: a zombie whose task was reclaimed cannot failover/retry it.

    TaskController.failover_or_fail_task is the on-failure reclaim path; fenced
    with the zombie's stale epoch it must be a no-op so it doesn't retry/fail a
    task a new owner now runs."""
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    claimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert claimed is not None
    stale_epoch = claimed[1]

    # Reclaim → re-run under a new epoch.
    await sm.retry(task_id)
    await db_session.execute(
        sa_update(JoySafeterTask)
        .where(JoySafeterTask.id == task_id)
        .values(status=JoySafeterTaskStatus.SCHEDULING.value, sandbox_id=sb)
    )
    await db_session.commit()
    reclaimed = await sm.claim_next_sandbox_task_for_running(sb)
    assert reclaimed is not None and reclaimed[1] > stale_epoch

    try:
        result = await TaskController.failover_or_fail_task(task_id, "zombie failover", expected_epoch=stale_epoch)
    finally:
        await engine.dispose()

    assert result is None, "a stale-epoch failover must be dropped"

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value, "the reclaimed task must keep running under its new owner"
    assert row.retry_count == 1, "the zombie failover must not consume another retry"


@pytest.mark.asyncio
async def test_failover_exhausted_retry_is_epoch_fenced(postgres_url, db_session, agent_id, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    sb = uuid.uuid4()
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        sandbox_id=sb,
        retry_count=2,
        max_retries=2,
        owner_epoch=10,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    try:
        result = await TaskController.failover_or_fail_task(task_id, "stale failure", expected_epoch=9)
    finally:
        await engine.dispose()

    assert result is None
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value
    assert row.error is None


@pytest.mark.asyncio
async def test_failover_exhausted_retry_marks_session_idle(postgres_url, db_session, agent_id, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        retry_count=2,
        max_retries=2,
        owner_epoch=10,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    try:
        result = await TaskController.failover_or_fail_task(task_id, "process crashed", expected_epoch=10)
    finally:
        await engine.dispose()

    assert result is None
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
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

    assert row.status == JoySafeterTaskStatus.FAILED.value
    assert row.error == "process crashed"
    assert session_row.status == "idle"
    assert session_row.stop_reason == {"type": "retries_exhausted"}
    assert event.payload == {"task_id": str(task_id), "stop_reason": {"type": "retries_exhausted"}}


@pytest.mark.asyncio
async def test_failover_completed_after_output_is_epoch_fenced(postgres_url, db_session, agent_id, monkeypatch):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        retry_count=0,
        max_retries=2,
        owner_epoch=20,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    db_session.add(
        JoySafeterSessionEvent(
            session_id=session.id,
            event_type="session.status_running",
            payload={"task_id": str(task_id)},
            seq=1,
        )
    )
    await db_session.commit()
    db_session.add(
        JoySafeterSessionEvent(
            session_id=session.id,
            event_type="agent.message",
            payload={"content": [{"type": "text", "text": "done"}]},
            seq=2,
        )
    )
    await db_session.commit()

    try:
        result = await TaskController.failover_or_fail_task(task_id, "stale failure", expected_epoch=19)
    finally:
        await engine.dispose()

    assert result is None
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.RUNNING.value
    assert row.completed_at is None


@pytest.mark.asyncio
async def test_failover_marks_completed_when_agent_output_already_persisted(
    postgres_url, db_session, agent_id, monkeypatch
):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        retry_count=0,
        max_retries=2,
        owner_epoch=30,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    db_session.add(
        JoySafeterSessionEvent(
            session_id=session_id,
            event_type="session.status_running",
            payload={"task_id": str(task_id)},
            seq=1,
        )
    )
    await db_session.commit()
    db_session.add(
        JoySafeterSessionEvent(
            session_id=session.id,
            event_type="agent.message",
            payload={"content": [{"type": "text", "text": "final answer"}]},
            seq=2,
        )
    )
    await db_session.commit()

    try:
        result = await TaskController.failover_or_fail_task(task_id, "process crashed", expected_epoch=30)
    finally:
        await engine.dispose()

    assert result is None
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.COMPLETED.value
    assert row.retry_count == 0


@pytest.mark.asyncio
async def test_failover_repairs_missing_agent_message_from_persisted_task_output(
    postgres_url, db_session, agent_id, monkeypatch
):
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    session = JoySafeterSession(agent_id=agent_id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
        output="final answer",
        retry_count=0,
        max_retries=2,
        owner_epoch=40,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    db_session.add(
        JoySafeterSessionEvent(
            session_id=session_id,
            event_type="session.status_running",
            payload={"task_id": str(task_id)},
            seq=1,
        )
    )
    await db_session.commit()

    try:
        result = await TaskController.failover_or_fail_task(task_id, "process crashed", expected_epoch=40)
    finally:
        await engine.dispose()

    assert result is None
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
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
    assert row.status == JoySafeterTaskStatus.COMPLETED.value
    assert row.retry_count == 0
    assert [(evt.event_type, evt.payload) for evt in events] == [
        ("session.status_running", {"task_id": str(task_id)}),
        ("agent.message", {"content": [{"type": "text", "text": "final answer"}]}),
        ("session.status_idle", {"task_id": str(task_id), "stop_reason": {"type": "end_turn"}}),
    ]


@pytest.mark.asyncio
async def test_archive_session_rejects_active_task_even_when_session_looks_idle(db_session, agent_id):
    session = JoySafeterSession(agent_id=agent_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        await SessionService(db_session).archive_session(session_id)

    assert exc_info.value.message == "Cannot archive session with active tasks"
    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.status == "idle"
    assert session_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_session_rejects_active_task_even_when_session_looks_idle(db_session, agent_id):
    session = JoySafeterSession(agent_id=agent_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent_id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    with pytest.raises(ConflictError) as exc_info:
        await SessionService(db_session).delete_session(session_id)

    assert exc_info.value.message == "Cannot delete session with active tasks"
    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert session_row.status == "idle"
    assert task_row.chat_session_id == session_id
