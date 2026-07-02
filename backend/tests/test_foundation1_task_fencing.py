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
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine


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
async def test_retry_clears_owner_epoch(db_session, agent_id):
    sm = JoySafeterTaskStateMachine(db_session)
    sb = uuid.uuid4()
    task_id = await _scheduling_task(db_session, agent_id, sb)
    await sm.claim_next_sandbox_task_for_running(sb)

    assert await sm.retry(task_id) is True
    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.owner_epoch is None, "retry must clear the fencing token alongside owner/lease"


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
