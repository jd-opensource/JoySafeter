import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.utils.datetime import utc_now


async def _cron_trigger(db_session):
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="P", slug=f"p-{uuid.uuid4()}", is_default=False)
    db_session.add_all([org, project])
    await db_session.flush()
    agent = JoySafeterAgent(name=f"a-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()
    trigger = JoySafeterTrigger(
        name=f"s-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now(),
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        concurrency_policy="replace",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.flush()
    return trigger, project, agent


async def _cron_trigger_with_active_task(db_session):
    trigger, project, agent = await _cron_trigger(db_session)
    task = JoySafeterTask(
        agent_id=agent.id,
        trigger_id=trigger.id,
        project_id=project.id,
        prompt="run",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    return trigger, project, task


@pytest.mark.asyncio
async def test_get_active_tasks_sees_active_run(db_session):
    # The concurrency-policy path (FORBID/REPLACE in the scheduler loop) calls
    # get_active_tasks and must see the trigger's active run; otherwise REPLACE
    # would start a duplicate instead of cancelling the prior run.
    trigger, _project, task = await _cron_trigger_with_active_task(db_session)
    svc = JoySafeterTriggerService(db_session)

    active = await svc.get_active_tasks(trigger.id)

    assert [str(t.id) for t in active] == [str(task.id)]


@pytest.mark.asyncio
async def test_delete_rejects_trigger_with_active_runs(db_session):
    # Hard-deleting a trigger while a task is still running breaks the production
    # chain: task.trigger_id is SET NULL by the FK, so run history and ownership
    # are lost while the resource continues executing.
    trigger, _project, task = await _cron_trigger_with_active_task(db_session)
    svc = JoySafeterTriggerService(db_session)

    with pytest.raises(ResourceConflictError) as exc_info:
        await svc.delete(trigger.id, trigger.project_id)

    assert exc_info.value.code == "TRIGGER_HAS_ACTIVE_RUNS"
    assert exc_info.value.data == {"trigger_id": str(trigger.id), "active_task_ids": [str(task.id)]}
    assert await svc.get(trigger.id, project_id=trigger.project_id) is not None
    persisted_task = await db_session.scalar(select(JoySafeterTask).where(JoySafeterTask.id == task.id))
    assert persisted_task is not None
    assert str(persisted_task.trigger_id) == str(trigger.id)


@pytest.mark.asyncio
async def test_delete_rejects_fresh_scheduler_claim_without_active_task(db_session):
    # A claimed cron trigger is already in the fire pipeline even before the task
    # row exists. Deleting it in that gap makes the scheduler create a task with a
    # missing trigger_id FK, surfacing as a 500 and potentially leaking a session.
    trigger, _project, _agent = await _cron_trigger(db_session)
    trigger.locked_by = "scheduler-worker-1"
    trigger.locked_at = utc_now()
    await db_session.commit()
    svc = JoySafeterTriggerService(db_session)

    with pytest.raises(ResourceConflictError) as exc_info:
        await svc.delete(trigger.id, trigger.project_id)

    assert exc_info.value.code == "TRIGGER_FIRE_IN_PROGRESS"
    assert exc_info.value.data["trigger_id"] == str(trigger.id)
    assert exc_info.value.data["locked_by"] == "scheduler-worker-1"
    assert await svc.get(trigger.id, project_id=trigger.project_id) is not None
