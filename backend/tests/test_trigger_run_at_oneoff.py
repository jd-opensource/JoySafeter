"""One-off (run_at) cron trigger: fires at its instant, then parks (next_run_at NULL)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.triggers import TriggerApplicationService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project


async def _seed(db_session):
    org = Organization(name=f"oneoff-org-{uuid.uuid4()}", slug=f"oneoff-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug=f"oneoff-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(name=f"oneoff-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    return org, project, agent


@pytest.mark.asyncio
async def test_one_off_sets_next_run_to_run_at_then_parks_after_fire(db_session):
    org, project, agent = await _seed(db_session)
    svc = TriggerApplicationService(db_session, credential_audit_actor=CredentialAuditActor.system("test"))
    run_at = datetime.now(timezone.utc) + timedelta(hours=1)

    trigger = await svc.create(
        name="once",
        type="cron",
        agent_id=agent.id,
        prompt_template="do it once",
        run_at=run_at,
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
    )
    assert trigger.cron_expr is None
    assert trigger.run_at is not None
    assert trigger.next_run_at == trigger.run_at  # armed to the one-off instant

    # After firing the slot, a one-off parks: no cron_expr → _next_run_or_pause = None.
    await svc.advance_after_fire(trigger.id, trigger.run_at, success=True)
    parked = await svc.get(trigger.id, project_id=project.id)
    assert parked is not None
    assert parked.next_run_at is None
    assert parked.last_fired_slot is not None
