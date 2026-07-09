import json
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


class _FakeCommandRedis:
    def __init__(self, *, cancel_receivers: int = 1, destroy_receivers: int = 1, owner: str | None = "owner-1"):
        self.cancel_receivers = cancel_receivers
        self.destroy_receivers = destroy_receivers
        self.owner = owner
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}
        self.blpop_timeouts: list[int] = []

    async def get(self, key: str) -> str | None:
        if key.startswith("joysafeter:sandbox_owner:"):
            return self.owner
        return None

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        if payload.get("type") == "cancel":
            receivers = self.cancel_receivers
        elif payload.get("type") == "destroy":
            receivers = self.destroy_receivers
        else:
            receivers = 1
        ack_key = payload.get("ack_key")
        if receivers > 0 and ack_key:
            self.acks[ack_key] = json.dumps({"command_id": payload.get("command_id"), "ok": True})
        return receivers

    async def blpop(self, key: str, timeout: int = 0):
        self.blpop_timeouts.append(timeout)
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


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
async def test_delete_agent_destroys_idle_session_sandbox_before_hard_delete(db_session, monkeypatch):
    redis = _FakeCommandRedis()
    agent = JoySafeterAgent(name=f"idle-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id

    session = JoySafeterSession(agent_id=agent_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    await delete_agent(agent_id, False, db_session, _auth_ctx())

    assert len(redis.published) == 1
    channel, payload = redis.published[0]
    assert channel == "joysafeter:cmd:owner-1"
    assert payload["type"] == "destroy"
    assert payload["sandbox_id"] == str(sandbox_id)
    assert redis.blpop_timeouts == [30]

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one_or_none()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is None
    assert sandbox_row.status == "destroyed"


@pytest.mark.asyncio
async def test_force_delete_agent_does_not_hard_delete_when_cancel_fails(db_session, monkeypatch):
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.RUNNING.value)
    agent_id = agent.id
    session_id = session.id
    task_id = task.id
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
async def test_force_delete_agent_keeps_agent_when_cancel_relay_fails(db_session, monkeypatch):
    redis = _FakeCommandRedis(cancel_receivers=0)
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
    task.sandbox_id = sandbox_id
    await db_session.commit()

    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, True, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "AGENT_REDIS_CANCEL_RELAY_FAILED",
        "message": "Failed to cancel agent task in sandbox runtime.",
        "data": {"agent_id": str(agent_id), "task_id": str(task_id), "sandbox_id": str(sandbox_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.published[0][1]["type"] == "cancel"

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is not None
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert sandbox_row.status == "running"


@pytest.mark.asyncio
async def test_force_delete_agent_cancels_and_destroys_sandbox_via_rust(db_session, monkeypatch):
    redis = _FakeCommandRedis()
    agent, session, task = await _agent_session_and_task(db_session, task_status=JoySafeterTaskStatus.RUNNING.value)
    agent_id = agent.id

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
    task.sandbox_id = sandbox_id
    await db_session.commit()

    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    await delete_agent(agent_id, True, db_session, _auth_ctx())

    command_types = [payload["type"] for _, payload in redis.published]
    assert command_types == ["cancel", "destroy"]
    assert redis.blpop_timeouts == [2, 30]

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one_or_none()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is None
    assert sandbox_row.status == "destroyed"


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
