"""Manual schedule trigger must be bounded by the owner's concurrency quota.

`POST /schedules/{id}/trigger` fires a schedule's task immediately, running it as
the schedule's stored owner. It previously passed enforce_user_quota=False, so a
project writer could fire another principal's schedule unbounded and quota-free —
an unbounded, quota-exempt task-spawn primitive. The manual trigger must enforce
the owner's per-user concurrency quota like any other submission.
"""

import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.schedules import trigger_schedule
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


async def _seed(db_session):
    org = Organization(name=f"sch-org-{uuid.uuid4()}", slug=f"sch-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug=f"sch-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(name=f"sch-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    schedule = JoySafeterSchedule(
        name="s",
        agent_id=agent.id,
        prompt="scan target",
        cron_expr="0 0 * * *",
        project_id=project.id,
        user_id="owner-user",
        org_id=org.id,
    )
    db_session.add(schedule)
    await db_session.commit()
    await db_session.refresh(schedule)
    return org, project, agent, schedule


@pytest.mark.asyncio
async def test_schedule_manual_trigger_enforces_owner_user_quota(db_session, monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_shared.cache.redis.RedisClient.get_client", staticmethod(lambda: redis))
    monkeypatch.setattr(settings, "max_concurrent_per_user", 1)

    org, project, agent, schedule = await _seed(db_session)

    # The owner is already at their per-user concurrent-task limit.
    await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id, prompt="busy", user_id="owner-user", org_id=org.id, project_id=project.id
    )

    auth = JoySafeterAuthContext(user_id="clicker", org_id=org.id, project_id=project.id, role=JoySafeterRole.MEMBER)
    with pytest.raises(AppError) as exc_info:
        await trigger_schedule(schedule.id, db_session, auth)

    payload = await handled_app_error_payload(exc_info.value, status_code=429)
    assert payload["code"] == "USER_TASK_LIMIT_EXCEEDED"
    assert redis.rpushed == [], "a quota-rejected manual trigger must not enqueue a task"
    # Only the pre-existing "busy" task exists; the trigger created none.
    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent.id)
    )
    assert total == 1
