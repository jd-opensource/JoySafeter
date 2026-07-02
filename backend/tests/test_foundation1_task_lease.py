"""Foundation 1 (fast reclaim) — running-task lease.

Failure scenario: the orchestrator instance running a task crashes. Today the
task sits in ``running`` until the ~2h ``timeout_sec`` upper bound elapses
before any watchdog reclaims it — a pentest session hangs for hours.

The owning instance stamps its ``owner_instance_id`` and a short
``lease_expires_at`` when it takes a task to ``running`` and renews the lease
while it holds it. A lease that lapses (owner gone) is reclaimed in seconds.
These tests pin that ownership contract at the DB-transition layer.
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine
from app.joysafeter_shared.utils.datetime import utc_now


@pytest_asyncio.fixture
async def agent_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"lease-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


async def _make_task(
    db_session,
    agent_id: uuid.UUID,
    *,
    status: JoySafeterTaskStatus,
    owner_instance_id: str | None = None,
    lease_expires_at=None,
) -> uuid.UUID:
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=status.value,
        owner_instance_id=owner_instance_id,
        lease_expires_at=lease_expires_at,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task.id


@pytest.mark.asyncio
async def test_transition_to_running_stamps_owner_and_future_lease(db_session, agent_id, monkeypatch):
    from app.joysafeter_shared.config.settings import joysafeter_config

    monkeypatch.setattr(joysafeter_config, "instance_id", "instance-A")
    monkeypatch.setattr(joysafeter_config, "task_lease_ttl_sec", 45)

    task_id = await _make_task(db_session, agent_id, status=JoySafeterTaskStatus.SCHEDULING)
    sm = JoySafeterTaskStateMachine(db_session)

    before = utc_now()
    ok = await sm.transition_to(task_id, JoySafeterTaskStatus.RUNNING)
    assert ok, "scheduling -> running must succeed"

    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert task.owner_instance_id == "instance-A", "the transitioning instance must claim ownership"
    assert task.lease_expires_at is not None, "a running task must carry a lease"
    assert task.lease_expires_at > before + timedelta(seconds=40), "lease must extend ~ttl into the future"


@pytest.mark.asyncio
async def test_claim_next_sandbox_task_stamps_owner_and_lease(db_session, agent_id, monkeypatch):
    from app.joysafeter_shared.config.settings import joysafeter_config

    monkeypatch.setattr(joysafeter_config, "instance_id", "instance-B")
    monkeypatch.setattr(joysafeter_config, "task_lease_ttl_sec", 45)

    sandbox_id = uuid.uuid4()
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
        sandbox_id=sandbox_id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    sm = JoySafeterTaskStateMachine(db_session)
    before = utc_now()
    claimed = await sm.claim_next_sandbox_task_for_running(sandbox_id)
    assert claimed is not None and claimed[0] == task.id, (
        "the scheduling task on this sandbox must be claimed to running"
    )

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task.id))).scalar_one()
    assert row.owner_instance_id == "instance-B", "the claiming instance must own the running task"
    assert row.lease_expires_at is not None and row.lease_expires_at > before + timedelta(seconds=40)


@pytest.mark.asyncio
async def test_renew_leases_extends_only_own_running_tasks(db_session, agent_id, monkeypatch):
    from app.joysafeter_shared.config.settings import joysafeter_config

    monkeypatch.setattr(joysafeter_config, "task_lease_ttl_sec", 45)
    now = utc_now()
    soon = now + timedelta(seconds=5)

    mine = await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.RUNNING, owner_instance_id="A", lease_expires_at=soon
    )
    theirs = await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.RUNNING, owner_instance_id="B", lease_expires_at=soon
    )
    # A pending task nominally owned by A must not be renewed (only running holds a live lease).
    mine_pending = await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.PENDING, owner_instance_id="A", lease_expires_at=soon
    )

    sm = JoySafeterTaskStateMachine(db_session)
    renewed = await sm.renew_leases("A")
    assert renewed == 1, "only the one running task owned by A should be renewed"

    rows = {
        r.id: r
        for r in (
            await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id.in_([mine, theirs, mine_pending])))
        ).scalars()
    }
    assert rows[mine].lease_expires_at > soon, "A's running lease must be pushed further out"
    assert rows[theirs].lease_expires_at == soon, "B's lease must be untouched"
    assert rows[mine_pending].lease_expires_at == soon, "a non-running task must not be renewed"


@pytest.mark.asyncio
async def test_find_lease_expired_running_returns_only_lapsed_running(db_session, agent_id):
    now = utc_now()
    past = now - timedelta(seconds=30)
    future = now + timedelta(seconds=30)

    expired = await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.RUNNING, owner_instance_id="dead", lease_expires_at=past
    )
    # Live lease — owner still renewing.
    await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.RUNNING, owner_instance_id="alive", lease_expires_at=future
    )
    # Terminal task with an old lease must never be reclaimed.
    await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.COMPLETED, owner_instance_id="dead", lease_expires_at=past
    )
    # Running but no lease yet stamped (legacy row) — not a lapse signal.
    await _make_task(
        db_session, agent_id, status=JoySafeterTaskStatus.RUNNING, owner_instance_id=None, lease_expires_at=None
    )

    sm = JoySafeterTaskStateMachine(db_session)
    found = await sm.find_lease_expired_running()

    assert found == [expired], "only the lapsed running task must be surfaced for reclaim"


@pytest.mark.asyncio
async def test_retry_clears_lease_ownership(db_session, agent_id):
    """Reclaiming a task (retry -> pending) must drop the dead owner's lease so
    the requeued task is not immediately re-flagged as lease-expired."""
    now = utc_now()
    task_id = await _make_task(
        db_session,
        agent_id,
        status=JoySafeterTaskStatus.RUNNING,
        owner_instance_id="dead",
        lease_expires_at=now - timedelta(seconds=30),
    )

    sm = JoySafeterTaskStateMachine(db_session)
    assert await sm.retry(task_id) is True

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.PENDING.value
    assert row.owner_instance_id is None, "retry must clear the dead owner"
    assert row.lease_expires_at is None, "retry must clear the stale lease"
    assert await sm.find_lease_expired_running() == [], "the requeued task must not look lease-expired"


class _FakeQueue:
    def __init__(self):
        self.pushed: list[uuid.UUID] = []

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        self.pushed.append(task_id)


@pytest.mark.asyncio
async def test_reclaim_expired_lease_requeues_abandoned_task(postgres_url, db_session, agent_id, monkeypatch):
    """End-to-end: a running task abandoned by a dead owner is reclaimed to
    pending and re-enqueued by the lease manager — not left hanging until the
    ~2h timeout."""
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController

    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    task_id = await _make_task(
        db_session,
        agent_id,
        status=JoySafeterTaskStatus.RUNNING,
        owner_instance_id="dead-instance",
        lease_expires_at=utc_now() - timedelta(seconds=60),
    )

    queue = _FakeQueue()
    controller = TaskController(queue)
    try:
        await controller._reclaim_expired_leases()
    finally:
        await engine.dispose()

    assert queue.pushed == [task_id], "the abandoned task must be re-enqueued exactly once"

    row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert row.status == JoySafeterTaskStatus.PENDING.value, "reclaimed task must return to pending"
    assert row.owner_instance_id is None and row.lease_expires_at is None, "reclaim must clear ownership"
    assert row.retry_count == 1, "reclaim consumes one retry via failover"
