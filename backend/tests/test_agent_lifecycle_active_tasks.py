import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.joysafeter_api.api.v1.agents import archive_agent, delete_agent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


async def _agent_session_and_task(db_session, *, task_status: str = JoySafeterTaskStatus.PENDING.value):
    agent = JoySafeterAgent(name=f"active-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        prompt="scan target",
        status=task_status,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return agent, session, task


@pytest.mark.asyncio
async def test_archive_agent_rejects_active_task_and_does_not_archive_sessions(db_session):
    agent, session, _task = await _agent_session_and_task(db_session)
    agent_id = agent.id
    session_id = session.id

    with pytest.raises(HTTPException) as exc_info:
        await archive_agent(agent_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Agent has active tasks. Stop or cancel them before archiving sessions."

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert agent_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"


@pytest.mark.asyncio
async def test_archive_sessions_for_agent_rejects_active_task_even_when_session_looks_idle(db_session):
    agent, session, _task = await _agent_session_and_task(db_session)
    agent_id = agent.id
    session_id = session.id

    with pytest.raises(ValueError) as exc_info:
        await JoySafeterAgentService(db_session).archive_sessions_for_agent(agent_id)

    assert str(exc_info.value) == "Agent has active tasks. Stop or cancel them before archiving sessions."
    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.archived_at is None
    assert session_row.status == "idle"


@pytest.mark.asyncio
async def test_force_delete_agent_does_not_hard_delete_when_cancel_fails(db_session, monkeypatch):
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.RUNNING.value)
    agent_id = agent.id
    session_id = session.id
    task_id = task.id

    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_sandbox_provider", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)

    async def cancel_noop(self, task_id):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_task_service.JoySafeterTaskService.cancel_task", cancel_noop
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent(agent_id, True, db_session, _auth_ctx())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to cancel all active tasks for agent"

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert agent_row is not None
    assert session_row is not None
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert task_row.chat_session_id == session_id


@pytest.mark.asyncio
async def test_delete_agent_race_active_task_becomes_409_not_500(db_session, monkeypatch):
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.PENDING.value)
    agent_id = agent.id
    session_id = session.id
    task_id = task.id

    async def hide_active_tasks_once(self, agent_id):
        return []

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.JoySafeterAgentService.list_active_tasks_for_agent",
        hide_active_tasks_once,
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent(agent_id, False, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Agent has active tasks. Cancel them before hard delete."

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert agent_row is not None
    assert task_row.chat_session_id == session_id
