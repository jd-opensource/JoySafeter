"""Session message dispatch failure must be explicit and compensated.

Failure scenario: `/sessions/{id}/events` persists `user.message`, creates a
task, marks the session running, then fails to enqueue because this API process
has no scheduler and Redis is unavailable. Returning 201 here is dangerous:
the user sees a submitted turn while the task may never run.
"""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_api.api.v1.sessions import (
    _publish_command_and_wait_for_ack,
    send_event,
    stop_session,
)
from app.joysafeter_api.api.v1.sessions import (
    delete_session as delete_session_endpoint,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_session import SendEventRequest, SingleEventRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _FakeScheduler:
    def __init__(self):
        self.pushed: list[uuid.UUID] = []

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        self.pushed.append(task_id)


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


class _FakeBroadcaster:
    def __init__(self):
        self.sent: list[tuple[uuid.UUID, dict]] = []
        self._channels: dict[uuid.UUID, list] = {}

    async def send(self, session_id: uuid.UUID, payload: dict) -> None:
        self.sent.append((session_id, payload))


class _FakeCommandRedis:
    def __init__(self, *, input_receivers: int = 1, cancel_receivers: int = 1):
        self.input_receivers = input_receivers
        self.cancel_receivers = cancel_receivers
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}

    async def get(self, key: str) -> str:
        assert key.startswith("joysafeter:sandbox_owner:")
        return "owner-1"

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        if not channel.startswith("joysafeter:cmd:"):
            return 0
        self.published.append((channel, payload))
        if payload.get("type") == "cancel":
            receivers = self.cancel_receivers
        else:
            receivers = self.input_receivers
        if receivers > 0 and payload.get("ack_key"):
            self.acks[payload["ack_key"]] = json.dumps(
                {
                    "command_id": payload.get("command_id", ""),
                    "ok": True,
                }
            )
        return receivers

    async def blpop(self, key: str, timeout: int = 0):
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


class _FakeAckRedis:
    def __init__(self, ack_payload=None, receivers: int = 1):
        self.ack_payload = ack_payload
        self.receivers = receivers
        self.published: list[tuple[str, dict]] = []

    async def publish(self, channel: str, command: str) -> int:
        self.published.append((channel, json.loads(command)))
        return self.receivers

    async def blpop(self, key: str, timeout: int = 0):
        if self.ack_payload is None:
            return None
        return key, json.dumps(self.ack_payload)


@pytest.mark.asyncio
async def test_user_message_enqueue_failure_returns_503_and_compensates(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"dispatch-failure-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.message",
                content=[{"type": "text", "text": "start scan"}],
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to enqueue task"

    db_session.expire_all()
    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert task.status == JoySafeterTaskStatus.FAILED.value
    assert "Failed to enqueue task" in (task.error or "")

    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.status == "idle"
    assert session_row.stop_reason == {"type": "error", "message": "Failed to enqueue task"}

    event_types = list(
        (
            await db_session.execute(
                select(JoySafeterSessionEvent.event_type)
                .where(JoySafeterSessionEvent.session_id == session_id)
                .order_by(JoySafeterSessionEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    assert event_types == [
        "user.message",
        "session.status_running",
        "session.status_idle",
    ]


@pytest.mark.asyncio
async def test_command_ack_wait_requires_matching_success_payload():
    ok = await _publish_command_and_wait_for_ack(
        _FakeAckRedis({"command_id": "cmd-1", "ok": True}),
        "joysafeter:cmd:owner-1",
        {"type": "cancel"},
        command_id="cmd-1",
        ack_key="joysafeter:cmd_ack:cmd-1",
    )
    assert ok is True

    failed = await _publish_command_and_wait_for_ack(
        _FakeAckRedis({"command_id": "cmd-1", "ok": False}),
        "joysafeter:cmd:owner-1",
        {"type": "cancel"},
        command_id="cmd-1",
        ack_key="joysafeter:cmd_ack:cmd-1",
    )
    assert failed is False

    mismatch = await _publish_command_and_wait_for_ack(
        _FakeAckRedis({"command_id": "other", "ok": True}),
        "joysafeter:cmd:owner-1",
        {"type": "cancel"},
        command_id="cmd-1",
        ack_key="joysafeter:cmd_ack:cmd-1",
    )
    assert mismatch is False

    timeout = await _publish_command_and_wait_for_ack(
        _FakeAckRedis(None),
        "joysafeter:cmd:owner-1",
        {"type": "cancel"},
        command_id="cmd-1",
        ack_key="joysafeter:cmd_ack:cmd-1",
    )
    assert timeout is False


@pytest.mark.asyncio
async def test_user_message_rejects_idle_session_with_active_task(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)

    agent = JoySafeterAgent(name=f"active-task-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="still active",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.message",
                content=[{"type": "text", "text": "new turn"}],
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    with pytest.raises(HTTPException) as exc_info:
        await send_event(req, session_id, db_session, auth_ctx)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Session has an active task; wait for completion before sending a new message"
    user_message_count = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterSessionEvent)
            .where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "user.message",
            )
        )
    ).scalar_one()
    assert user_message_count == 0


@pytest.mark.asyncio
async def test_user_message_idempotent_retry_after_enqueue_failure_stays_503(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"dispatch-failure-idem-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.message",
                content=[{"type": "text", "text": "start scan"}],
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )
    key = f"msg-{uuid.uuid4()}"

    try:
        with pytest.raises(HTTPException) as first_exc:
            await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
        with pytest.raises(HTTPException) as second_exc:
            await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
    finally:
        await engine.dispose()

    assert first_exc.value.status_code == 503
    assert second_exc.value.status_code == 503
    assert second_exc.value.detail == "Failed to enqueue task"

    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    assert task_count == 1
    user_message_count = await db_session.scalar(
        select(func.count())
        .select_from(JoySafeterSessionEvent)
        .where(
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "user.message",
        )
    )
    assert user_message_count == 1


@pytest.mark.asyncio
async def test_user_message_idempotency_key_prevents_duplicate_task(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    scheduler = _FakeScheduler()
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: scheduler)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"dispatch-idem-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.message",
                content=[{"type": "text", "text": "start scan"}],
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )
    key = f"msg-{uuid.uuid4()}"

    try:
        first = await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
        second = await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
    finally:
        await engine.dispose()

    assert first["events"][0]["id"] == second["events"][0]["id"]
    assert len(scheduler.pushed) == 1

    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    assert task_count == 1

    user_message_count = await db_session.scalar(
        select(func.count())
        .select_from(JoySafeterSessionEvent)
        .where(
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "user.message",
        )
    )
    assert user_message_count == 1


@pytest.mark.asyncio
async def test_user_message_rejects_idempotency_key_reuse_for_different_message(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    scheduler = _FakeScheduler()
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: scheduler)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"dispatch-idem-reuse-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )
    key = f"msg-{uuid.uuid4()}"
    first = SendEventRequest(
        events=[SingleEventRequest(type="user.message", content=[{"type": "text", "text": "first"}])]
    )
    second = SendEventRequest(
        events=[SingleEventRequest(type="user.message", content=[{"type": "text", "text": "second"}])]
    )

    try:
        await send_event(first, session_id, db_session, auth_ctx, idempotency_key=key)
        with pytest.raises(HTTPException) as exc_info:
            await send_event(second, session_id, db_session, auth_ctx, idempotency_key=key)
    finally:
        await engine.dispose()

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Idempotency-Key was already used for a different message"
    assert len(scheduler.pushed) == 1


@pytest.mark.asyncio
async def test_tool_confirmation_fallback_enqueues_via_redis_without_local_scheduler(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"control-fallback-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.tool_confirmation",
                tool_use_id="call-1",
                approved=True,
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    try:
        await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert task.status == JoySafeterTaskStatus.PENDING.value
    assert "User approved tool call event" in task.prompt
    assert redis.rpushed == [("joysafeter:global_queue", str(task.id))]


@pytest.mark.asyncio
async def test_tool_confirmation_fallback_failure_returns_503_and_marks_task_failed(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"control-fallback-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(
        events=[
            SingleEventRequest(
                type="user.tool_confirmation",
                tool_use_id="call-1",
                approved=True,
            )
        ]
    )
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to deliver tool confirmation"

    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert task.status == JoySafeterTaskStatus.FAILED.value
    assert "Failed to enqueue fallback task for tool_confirmation" in (task.error or "")


@pytest.mark.asyncio
async def test_interrupt_requires_cancel_delivery_for_running_session(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = _FakeCommandRedis(input_receivers=1, cancel_receivers=0)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"interrupt-cancel-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running", last_sandbox_id=uuid.uuid4())
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    req = SendEventRequest(events=[SingleEventRequest(type="user.interrupt")])
    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to deliver interrupt"
    assert [payload["type"] for _channel, payload in redis.published] == ["input", "cancel"]

    event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "user.interrupt",
            )
        )
    ).scalar_one()
    assert event.processed_at is not None, "the input half was delivered and should not be replayed as pending"


@pytest.mark.asyncio
async def test_stop_session_does_not_mark_idle_when_task_cancel_write_fails(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_redis_coordinator", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)

    async def fake_update_task_error(self, task_id, error, new_status, expected_epoch=None):
        return False

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_task_service.JoySafeterTaskService.update_task_error",
        fake_update_task_error,
    )

    agent = JoySafeterAgent(name=f"stop-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    with pytest.raises(HTTPException) as exc_info:
        await stop_session(session_id, db_session, auth_ctx)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to cancel all active tasks"

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    idle_events = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterSessionEvent)
            .where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "session.status_idle",
            )
        )
    ).scalar_one()
    assert session_row.status == "running"
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert idle_events == 0


@pytest.mark.asyncio
async def test_stop_session_marks_idle_only_after_active_tasks_cancelled(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_bridge_registry", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_redis_coordinator", lambda: None)
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: None)

    agent = JoySafeterAgent(name=f"stop-ok-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    response = await stop_session(session_id, db_session, auth_ctx)

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    idle_event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "session.status_idle",
            )
        )
    ).scalar_one()

    assert response["status"] == "idle"
    assert response["cancelled_tasks"] == 1
    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
    assert session_row.status == "idle"
    assert session_row.stop_reason == {"type": "cancelled"}
    assert idle_event.payload == {"stop_reason": {"type": "cancelled"}}


@pytest.mark.asyncio
async def test_delete_session_rejects_active_task_before_deleted_broadcast(db_session, monkeypatch):
    broadcaster = _FakeBroadcaster()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_session_broadcaster", lambda: broadcaster)

    agent = JoySafeterAgent(name=f"delete-active-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_session_endpoint(session_id, db_session, auth_ctx)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Session has an active task; stop it before deleting session"
    assert broadcaster.sent == []

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert session_row.status == "idle"
    assert task_row.chat_session_id == session_id
