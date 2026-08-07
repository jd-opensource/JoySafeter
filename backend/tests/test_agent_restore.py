import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.utils.datetime import utc_now


async def _project_and_agent(db_session, *, name: str) -> tuple[Project, JoySafeterAgent]:
    org = Organization(id=f"org-{uuid.uuid4()}", name=f"{name} Org", slug=f"{name.lower()}-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name=name, slug=f"{name.lower()}-{uuid.uuid4()}")
    db_session.add_all([org, project])
    await db_session.commit()
    await db_session.refresh(project)
    agent = JoySafeterAgent(name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return project, agent


async def _paused_cron_trigger(db_session, *, project: Project, agent: JoySafeterAgent) -> JoySafeterTrigger:
    trigger = JoySafeterTrigger(
        name=f"cron-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="scheduled audit",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=None,  # simulate the post-archive paused state
        project_id=project.id,
        user_id="trigger-owner",
        org_id=project.org_id,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


@pytest.mark.asyncio
async def test_resume_after_agent_restore_rearms_enabled_cron_trigger(db_session):
    project, agent = await _project_and_agent(db_session, name="ResumeRearm")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    trigger_id = trigger.id

    await JoySafeterTriggerService(db_session).resume_after_agent_restore(agent.id)
    await db_session.commit()

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))).scalar_one()
    assert row.next_run_at is not None
    assert row.next_run_at > utc_now() - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_resume_after_agent_restore_keeps_disabled_trigger_paused(db_session):
    project, agent = await _project_and_agent(db_session, name="ResumeDisabled")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    trigger.enabled = False
    await db_session.commit()
    trigger_id = trigger.id

    await JoySafeterTriggerService(db_session).resume_after_agent_restore(agent.id)
    await db_session.commit()

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))).scalar_one()
    assert row.next_run_at is None
