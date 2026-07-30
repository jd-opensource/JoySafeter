"""Foundation 3 (tenancy) — task submitter identity + per-user admission.

Each task records the submitting user's identity (user_id, org_id) for
attribution/audit, and a single user's live (non-terminal) task count backs
per-user admission control so one user cannot consume the whole fleet budget.
user_id/org_id are plain columns (no FK), so tests use arbitrary id strings.
"""

import uuid

import pytest
import pytest_asyncio

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService


@pytest_asyncio.fixture
async def agent_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"test-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


@pytest.mark.asyncio
async def test_create_task_records_user_and_org(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    task = await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-1", org_id="org-1")
    fetched = await db_session.get(JoySafeterTask, task.id)
    assert fetched is not None
    assert fetched.user_id == "user-1"
    assert fetched.org_id == "org-1"


@pytest.mark.asyncio
async def test_counts_active_tasks_for_user(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    for _ in range(3):
        await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-1")

    assert await svc.count_active_tasks_for_user("user-1") == 3


@pytest.mark.asyncio
async def test_empty_user_counts_zero(db_session):
    svc = JoySafeterTaskService(db_session)
    assert await svc.count_active_tasks_for_user("nobody") == 0


@pytest.mark.asyncio
async def test_terminal_tasks_do_not_count_for_user(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    live = await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-1")
    done = await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-1")

    done_row = await db_session.get(JoySafeterTask, done.id)
    done_row.status = JoySafeterTaskStatus.COMPLETED.value
    await db_session.commit()

    assert await svc.count_active_tasks_for_user("user-1") == 1, (
        "only the non-terminal task counts against the user budget"
    )
    assert live.id != done.id


@pytest.mark.asyncio
async def test_other_user_tasks_not_counted(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-1")
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-2")
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id="user-2")

    assert await svc.count_active_tasks_for_user("user-1") == 1
    assert await svc.count_active_tasks_for_user("user-2") == 2, (
        "the count must be scoped to one user; another user's tasks are invisible"
    )
