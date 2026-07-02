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
