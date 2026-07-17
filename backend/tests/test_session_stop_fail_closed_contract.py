"""Session-stop must fail closed when the runtime cancel relay is not confirmed.

``POST /sessions/{id}/stop`` cancels every active task in the session. If the
Redis relay that actually stops the sandbox is not confirmed (owner offline, no
receivers, ack timeout), the endpoint must NOT report the session idle and must
NOT mark the task cancelled in the DB — otherwise the operator sees "stopped"
while the pentest tooling keeps running against a real target. This mirrors the
already-hardened ``POST /tasks/{id}/cancel`` path so the two cannot drift.
"""

import json
import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_api.api.v1.sessions import stop_session
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _FakeCommandRedis:
    def __init__(self, *, cancel_receivers: int = 1):
        self.cancel_receivers = cancel_receivers
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}

    async def get(self, key: str) -> str:
        assert key.startswith("joysafeter:sandbox_owner:")
        return "owner-1"

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        if self.cancel_receivers > 0 and payload.get("ack_key"):
            self.acks[payload["ack_key"]] = json.dumps({"command_id": payload.get("command_id", ""), "ok": True})
        return self.cancel_receivers

    async def blpop(self, key: str, timeout: int = 0):
        payload = self.acks.pop(key, None)
        return None if payload is None else (key, payload)


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _running_session_with_task(db_session) -> tuple[JoySafeterSession, JoySafeterTask, JoySafeterSandbox]:
    agent = JoySafeterAgent(name=f"session-stop-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.flush()
    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=f"sandbox-{uuid.uuid4()}",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    db_session.add(sandbox)
    await db_session.flush()
    session.last_sandbox_id = sandbox.id
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        sandbox_id=sandbox.id,
        prompt="long running scan",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    return session, task, sandbox


@pytest.mark.asyncio
async def test_session_stop_does_not_mark_idle_when_cancel_relay_fails(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    redis = _FakeCommandRedis(cancel_receivers=0)  # relay not delivered
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    session, task, _sandbox = await _running_session_with_task(db_session)
    session_id, task_id = session.id, task.id

    with pytest.raises(AppError) as exc_info:
        await stop_session(session_id, db_session, _auth_ctx())

    assert exc_info.value.code in {"TASK_CANCEL_REDIS_RELAY_FAILED", "SESSION_STOP_CANCEL_TASKS_FAILED"}

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value, "task must not be marked cancelled if relay failed"
    assert session_row.status == "running", "session must not be reported idle if the sandbox was not stopped"


@pytest.mark.asyncio
async def test_session_stop_cancels_task_and_idles_session_when_relay_confirmed(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    redis = _FakeCommandRedis(cancel_receivers=1)  # relay confirmed
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    session, task, sandbox = await _running_session_with_task(db_session)
    session_id, task_id = session.id, task.id

    result = await stop_session(session_id, db_session, _auth_ctx())

    assert result["status"] == "idle"
    assert result["cancelled_tasks"] == 1
    # A real cancel command was relayed to the sandbox owner.
    cancels = [p for _, p in redis.published if p.get("type") == "cancel"]
    assert len(cancels) == 1 and cancels[0]["sandbox_id"] == str(sandbox.id)

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
    assert session_row.status == "idle"
