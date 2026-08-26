"""Manual trigger run must be bounded by the owner's concurrency quota.

``POST /triggers/{id}/run`` fires a trigger's task immediately, running it as the
trigger's stored owner. It must enforce the owner's per-user concurrency quota so
a project writer cannot fire another principal's trigger unbounded and quota-free.
"""

import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import Request
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.triggers import run_trigger_now
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, OrganizationId, ProjectId, TriggerId, UserId


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


def _fake_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


async def _seed(db_session):
    owner_user_id = UserId.new()
    org = Organization(id=OrganizationId.new(), name=f"trg-org-{uuid.uuid4()}", slug=f"trg-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(id=ProjectId.new(), org_id=org.id, name="P", slug=f"trg-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(id=AgentId.new(), name=f"trg-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    trigger = JoySafeterTrigger(
        id=TriggerId.new(),
        name="s",
        type="cron",
        agent_id=agent.id,
        prompt_template="scan target",
        cron_expr="0 0 * * *",
        timezone="UTC",
        project_id=project.id,
        user_id=owner_user_id,
        org_id=org.id,
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return org, project, agent, trigger, owner_user_id


@pytest.mark.asyncio
async def test_trigger_manual_run_enforces_owner_user_quota(db_session, monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_shared.cache.redis.RedisClient.get_client", staticmethod(lambda: redis))
    monkeypatch.setattr(settings, "max_concurrent_per_user", 1)

    org, project, agent, trigger, owner_user_id = await _seed(db_session)

    # The owner is already at their per-user concurrent-task limit.
    await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id, prompt="busy", user_id=owner_user_id, org_id=org.id, project_id=project.id
    )

    auth = JoySafeterAuthContext(
        user_id=UserId.new(),
        org_id=org.id,
        project_id=project.id,
        role=JoySafeterRole.MEMBER,
    )
    with pytest.raises(AppError) as exc_info:
        await run_trigger_now(_fake_request(), trigger.id, db_session, auth)

    payload = await handled_app_error_payload(exc_info.value, status_code=429)
    assert payload["code"] == "USER_TASK_LIMIT_EXCEEDED"
    assert redis.rpushed == [], "a quota-rejected manual run must not enqueue a task"
    # Only the pre-existing "busy" task exists; the run created none.
    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent.id)
    )
    assert total == 1
