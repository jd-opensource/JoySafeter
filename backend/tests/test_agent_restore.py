import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.joysafeter_api.api.v1.agents import unarchive_agent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import as_uuid
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


def _write_ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


@pytest.mark.asyncio
async def test_unarchive_clears_archived_at_and_rearms_triggers(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreE2E")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    # Capture PKs before any expire_all(): reading an expired ORM attribute
    # triggers a synchronous reload inside async -> MissingGreenlet.
    agent_id = agent.id
    trigger_id = trigger.id
    ctx = _write_ctx(project.id, project.org_id)
    svc = JoySafeterAgentService(db_session)

    archived, _ = await svc.archive_agent_with_sessions(agent_id, project_id=ctx.project_id)
    assert archived is True
    db_session.expire_all()
    archived_row = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
    ).scalar_one()
    assert archived_row.archived_at is not None
    paused = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert paused.next_run_at is None

    result = await unarchive_agent(agent_id, db_session, ctx)
    assert result == {"status": "active"}

    db_session.expire_all()
    restored = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    rearmed = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert restored.archived_at is None
    assert rearmed.next_run_at is not None


@pytest.mark.asyncio
async def test_unarchive_leaves_terminated_sessions_archived(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreSessions")
    session = JoySafeterSession(agent_id=agent.id, project_id=project.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    agent_id = agent.id
    session_id = session.id

    svc = JoySafeterAgentService(db_session)
    archived, archived_session_ids = await svc.archive_agent_with_sessions(agent_id, project_id=project.id)
    assert archived is True
    assert archived_session_ids == [session_id]

    restored = await svc.restore_agent(agent_id, project_id=project.id)
    assert restored is True

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.archived_at is not None
    assert session_row.status == "terminated"


@pytest.mark.asyncio
async def test_unarchive_does_not_rearm_cron_when_project_triggers_are_paused(db_session):
    project, agent = await _project_and_agent(db_session, name="RestorePausedProject")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    agent.archived_at = utc_now()
    project.triggers_paused = True
    await db_session.commit()
    agent_id = agent.id
    trigger_id = trigger.id

    restored = await JoySafeterAgentService(db_session).restore_agent(agent_id, project_id=project.id)
    assert restored is True

    db_session.expire_all()
    trigger_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert trigger_row.next_run_at is None


@pytest.mark.asyncio
async def test_unarchive_is_idempotent_on_active_agent(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreIdempotent")
    agent_id = agent.id
    ctx = _write_ctx(project.id, project.org_id)

    result = await unarchive_agent(agent_id, db_session, ctx)
    assert result == {"status": "active"}
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_unarchive_missing_agent_raises_404(db_session):
    project, _agent = await _project_and_agent(db_session, name="RestoreMissing")
    ctx = _write_ctx(project.id, project.org_id)
    missing_id = as_uuid(uuid.uuid4())

    with pytest.raises(AppError) as exc_info:
        await unarchive_agent(missing_id, db_session, ctx)  # type: ignore[arg-type]

    assert exc_info.value.code == "AGENT_NOT_FOUND"
