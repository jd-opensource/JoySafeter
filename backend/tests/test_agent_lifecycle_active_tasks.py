import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.agents import archive_agent, delete_agent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


class _StopFailingSandboxProvider:
    def __init__(self):
        self.stopped: list[str] = []

    async def stop(self, external_id: str) -> None:
        self.stopped.append(external_id)
        raise RuntimeError("provider stop failed")


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

    with pytest.raises(AppError) as exc_info:
        await archive_agent(agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks. Stop or cancel them before archiving sessions.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

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
async def test_delete_agent_rejects_active_task_with_structured_task_ids(db_session):
    agent, session, task = await _agent_session_and_task(db_session)
    agent_id = agent.id
    session_id = session.id
    task_id = task.id

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, False, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks (pending/running). Use ?force=true to force delete.",
        "data": {"agent_id": str(agent_id), "active_task_ids": [str(task_id)]},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert agent_row is not None
    assert task_row.chat_session_id == session_id


@pytest.mark.asyncio
async def test_force_delete_agent_does_not_hard_delete_when_cancel_fails(db_session, monkeypatch):
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.RUNNING.value)
    agent_id = agent.id
    session_id = session.id
    task_id = task.id

    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_sandbox_provider", lambda: None)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

    async def cancel_noop(self, task_id):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_task_service.JoySafeterTaskService.cancel_task", cancel_noop
    )

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, True, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "AGENT_FORCE_CANCEL_ACTIVE_TASKS_FAILED",
        "message": "Failed to cancel all active tasks for agent",
        "data": {"agent_id": str(agent_id), "active_task_ids": [str(task_id)]},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

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
async def test_force_delete_agent_keeps_agent_when_sandbox_stop_fails(db_session, monkeypatch):
    provider = _StopFailingSandboxProvider()
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.RUNNING.value)
    agent_id = agent.id
    task_id = task.id

    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="running",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id
    external_id = sandbox.external_id
    task.sandbox_id = sandbox_id
    await db_session.commit()

    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_sandbox_provider", lambda: provider)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, True, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "AGENT_SANDBOX_STOP_FAILED",
        "message": "Agent could not be deleted because sandbox cleanup failed.",
        "data": {"agent_id": str(agent_id), "sandbox_id": str(sandbox_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert provider.stopped == [external_id]

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is not None
    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
    assert sandbox_row.status == "running"


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

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, False, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks. Cancel them before hard delete.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert agent_row is not None
    assert task_row.chat_session_id == session_id
