"""Tenancy: task submitter identity + per-user admission.

Each task records the submitting user's identity (user_id, org_id) for
attribution/audit, and a single user's live (non-terminal) task count backs
per-user admission control so one user cannot consume the whole fleet budget.
The identity columns are not foreign-key constrained, but still retain their
domain-specific typed IDs.
"""

import uuid

import pytest
import pytest_asyncio

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.ids import AgentId, OrganizationId, UserId


@pytest_asyncio.fixture
async def agent_id(db_session) -> AgentId:
    agent = JoySafeterAgent(id=AgentId.new(), name=f"test-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


@pytest.mark.asyncio
async def test_create_task_records_user_and_org(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    user_id = UserId.new()
    org_id = OrganizationId.new()
    task = await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_id, org_id=org_id)
    fetched = await db_session.get(JoySafeterTask, task.id)
    assert fetched is not None
    assert fetched.user_id == user_id
    assert fetched.org_id == org_id


@pytest.mark.asyncio
async def test_counts_active_tasks_for_user(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    user_id = UserId.new()
    for _ in range(3):
        await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_id)

    assert await svc.count_active_tasks_for_user(user_id) == 3


@pytest.mark.asyncio
async def test_empty_user_counts_zero(db_session):
    svc = JoySafeterTaskService(db_session)
    assert await svc.count_active_tasks_for_user(UserId.new()) == 0


@pytest.mark.asyncio
async def test_terminal_tasks_do_not_count_for_user(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    user_id = UserId.new()
    live = await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_id)
    done = await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_id)

    done_row = await db_session.get(JoySafeterTask, done.id)
    done_row.status = JoySafeterTaskStatus.COMPLETED.value
    await db_session.commit()

    assert await svc.count_active_tasks_for_user(user_id) == 1, (
        "only the non-terminal task counts against the user budget"
    )
    assert live.id != done.id


@pytest.mark.asyncio
async def test_other_user_tasks_not_counted(db_session, agent_id):
    svc = JoySafeterTaskService(db_session)
    user_a = UserId.new()
    user_b = UserId.new()
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_a)
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_b)
    await svc.create_task(agent_id=agent_id, prompt="scan", user_id=user_b)

    assert await svc.count_active_tasks_for_user(user_a) == 1
    assert await svc.count_active_tasks_for_user(user_b) == 2, (
        "the count must be scoped to one user; another user's tasks are invisible"
    )
