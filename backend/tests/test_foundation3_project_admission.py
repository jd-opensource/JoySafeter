"""Foundation 3 (tenancy) — per-project concurrent-task admission control.

A single project (the tenant boundary) must not be able to occupy unbounded
orchestrator/sandbox capacity: one noisy tenant would starve every other tenant
on the shared HA fleet. Admission is gated on the number of *non-terminal* tasks
already owned by the project.

The load-bearing logic is the count of active tasks scoped to a project. It is
tested here against real Postgres (the status filter and project scoping must
match the DB's view, not an in-memory guess). The HTTP 429 mapping in the API is
thin glue placed after the idempotency short-circuit so retries are never gated.
"""

import uuid

import pytest
import pytest_asyncio

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_a(db_session) -> str:
    return await _make_project(db_session)


@pytest_asyncio.fixture
async def project_b(db_session) -> str:
    return await _make_project(db_session)


@pytest_asyncio.fixture
async def agent_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"test-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent.id


@pytest.mark.asyncio
async def test_counts_active_tasks_for_project(db_session, agent_id, project_a):
    svc = JoySafeterTaskService(db_session)
    for _ in range(3):
        await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_a)

    assert await svc.count_active_tasks_for_project(project_a) == 3


@pytest.mark.asyncio
async def test_empty_project_counts_zero(db_session, project_a):
    svc = JoySafeterTaskService(db_session)
    assert await svc.count_active_tasks_for_project(project_a) == 0


@pytest.mark.asyncio
async def test_terminal_tasks_do_not_count(db_session, agent_id, project_a):
    svc = JoySafeterTaskService(db_session)
    live = await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_a)
    done = await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_a)

    # A terminal task must drop out of the live budget. Set the status directly:
    # the counter's status filter is what's under test, not the ownership
    # protocol the state machine enforces on real terminal transitions.
    done_row = await db_session.get(JoySafeterTask, done.id)
    done_row.status = JoySafeterTaskStatus.COMPLETED.value
    await db_session.commit()

    assert (
        await svc.count_active_tasks_for_project(project_a) == 1
    ), "only the non-terminal task counts against the project budget"
    assert live.id != done.id


@pytest.mark.asyncio
async def test_other_project_tasks_not_counted(db_session, agent_id, project_a, project_b):
    svc = JoySafeterTaskService(db_session)
    await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_a)
    await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_b)
    await svc.create_task(agent_id=agent_id, prompt="scan", project_id=project_b)

    assert await svc.count_active_tasks_for_project(project_a) == 1
    assert (
        await svc.count_active_tasks_for_project(project_b) == 2
    ), "the count must be scoped to one tenant; another project's tasks are invisible"


@pytest.mark.asyncio
async def test_agent_task_helpers_are_project_scoped_when_requested(db_session, agent_id, project_a, project_b):
    svc = JoySafeterTaskService(db_session)
    task_a = await svc.create_task(agent_id=agent_id, prompt="scan a", project_id=project_a)
    task_b = await svc.create_task(agent_id=agent_id, prompt="scan b", project_id=project_b)
    task_b_row = await db_session.get(JoySafeterTask, task_b.id)
    task_b_row.status = JoySafeterTaskStatus.COMPLETED.value
    await db_session.commit()

    tasks_a, has_more_a = await svc.list_tasks_by_agent(agent_id, project_id=project_a)
    tasks_b, has_more_b = await svc.list_tasks_by_agent(agent_id, project_id=project_b)

    assert [str(task.id) for task in tasks_a] == [str(task_a.id)]
    assert [str(task.id) for task in tasks_b] == [str(task_b.id)]
    assert has_more_a is False
    assert has_more_b is False
    assert await svc.agent_has_active_tasks(agent_id, project_id=project_a) is True
    assert await svc.agent_has_active_tasks(agent_id, project_id=project_b) is False


@pytest.mark.asyncio
async def test_limit_falls_back_to_default_when_unset(db_session, project_a):
    svc = JoySafeterTaskService(db_session)
    # No per-project override set -> the caller's global default applies.
    assert await svc.resolve_project_task_limit(project_a, default_limit=5) == 5


@pytest.mark.asyncio
async def test_per_project_override_wins_over_default(db_session, project_a):
    svc = JoySafeterTaskService(db_session)
    project = await db_session.get(Project, project_a)
    project.max_concurrent_tasks = 20
    await db_session.commit()

    assert (
        await svc.resolve_project_task_limit(project_a, default_limit=5) == 20
    ), "a project's own limit must override the global default"
