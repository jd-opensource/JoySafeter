import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_shared.utils.datetime import utc_now


async def _schedule_with_active_task(db_session):
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="P", slug=f"p-{uuid.uuid4()}", is_default=False)
    db_session.add_all([org, project])
    await db_session.flush()
    agent = JoySafeterAgent(name=f"a-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()
    schedule = JoySafeterSchedule(
        name=f"s-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt="run",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now(),
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        concurrency_policy="replace",
    )
    db_session.add(schedule)
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent.id,
        schedule_id=schedule.id,
        project_id=project.id,
        prompt="run",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    return schedule, project, task


@pytest.mark.asyncio
async def test_get_active_tasks_unscoped_sees_active_run(db_session):
    # The concurrency-policy path calls get_active_tasks WITHOUT project_id and
    # must see the schedule's active run; otherwise REPLACE would start a
    # duplicate instead of cancelling the prior run.
    schedule, _project, task = await _schedule_with_active_task(db_session)
    svc = JoySafeterScheduleService(db_session)

    active = await svc.get_active_tasks(schedule.id)

    assert [str(t.id) for t in active] == [str(task.id)]


@pytest.mark.asyncio
async def test_get_active_tasks_scope_miss_returns_empty(db_session):
    # A mismatched project_id scopes the lookup out entirely (API-listing
    # contract). This is why concurrency-policy callers must pass project_id=None.
    schedule, _project, _task = await _schedule_with_active_task(db_session)
    svc = JoySafeterScheduleService(db_session)

    active = await svc.get_active_tasks(schedule.id, project_id=f"proj-{uuid.uuid4()}")

    assert list(active) == []
