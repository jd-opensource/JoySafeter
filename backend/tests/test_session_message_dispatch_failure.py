"""Session message dispatch failure must be explicit and compensated.

Failure scenario: `/sessions/{id}/events` persists `user.message`, creates a
task, marks the session running, then fails to enqueue because this API process
has no scheduler and Redis is unavailable. Returning 201 here is dangerous:
the user sees a submitted turn while the task may never run.
"""

import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
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
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_session import SendEventRequest, SingleEventRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


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
    def __init__(self, *, input_receivers: int = 1, cancel_receivers: int = 1, destroy_receivers: int = 1):
        self.input_receivers = input_receivers
        self.cancel_receivers = cancel_receivers
        self.destroy_receivers = destroy_receivers
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}
        self.blpop_timeouts: list[int] = []

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
        elif payload.get("type") == "destroy":
            receivers = self.destroy_receivers
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
        self.blpop_timeouts.append(timeout)
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


class _AckWaitFailingRedis(_FakeAckRedis):
    async def blpop(self, key: str, timeout: int = 0):
        raise RuntimeError("ack wait failed")


@pytest.mark.asyncio
async def test_user_message_enqueue_failure_returns_503_and_compensates(
    postgres_url,
    db_session,
    monkeypatch,
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
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
        with pytest.raises(AppError) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    db_session.expire_all()
    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"session_id": str(session_id), "task_id": str(task.id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert task.status == JoySafeterTaskStatus.FAILED.value
    assert "Failed to enqueue task" in (task.error or "")

    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert session_row.status == "idle"
    assert session_row.stop_reason == {
        "type": "error",
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"session_id": str(session_id), "task_id": str(task.id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

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
async def test_command_ack_wait_failure_logs_structured_boundary_error(caplog):
    with caplog.at_level("DEBUG", logger="app.joysafeter_api.runtime_commands"):
        result = await _publish_command_and_wait_for_ack(
            _AckWaitFailingRedis({"command_id": "cmd-1", "ok": True}),
            "joysafeter:cmd:owner-1",
            {"type": "cancel"},
            command_id="cmd-1",
            ack_key="joysafeter:cmd_ack:cmd-1",
        )

    assert result is False
    errors = [getattr(record, "error", None) for record in caplog.records if getattr(record, "error", None)]
    assert errors
    error = errors[0]
    assert error["code"] == "SESSION_REDIS_COMMAND_ACK_WAIT_FAILED"
    assert error["data"]["boundary"] == "session_api"
    assert error["data"]["operation"] == "wait_command_ack"
    assert error["data"]["command_id"] == "cmd-1"
    assert error["detail"] == "RuntimeError"


@pytest.mark.asyncio
async def test_user_message_rejects_idle_session_with_active_task(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

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

    with pytest.raises(AppError) as exc_info:
        await send_event(req, session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ACTIVE_TASK",
        "message": "Session has an active task; wait for completion before sending a new message",
        "source": "api",
        "retryable": True,
        "user_action": "retry",
        "data": {
            "session_id": str(session_id),
            "active_task_ids": [str(task.id)],
        },
    }
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
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
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
        with pytest.raises(AppError) as first_exc:
            await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
        with pytest.raises(AppError) as second_exc:
            await send_event(req, session_id, db_session, auth_ctx, idempotency_key=key)
    finally:
        await engine.dispose()

    assert (await handled_app_error_payload(first_exc.value, status_code=503))["code"] == "TASK_ENQUEUE_FAILED"

    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert await handled_app_error_payload(second_exc.value, status_code=503) == {
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"session_id": str(session_id), "task_id": str(task.id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
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
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
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
    assert len(redis.rpushed) == 1

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
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
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
        with pytest.raises(AppError) as exc_info:
            await send_event(second, session_id, db_session, auth_ctx, idempotency_key=key)
    finally:
        await engine.dispose()

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_IDEMPOTENCY_KEY_MISMATCH",
        "message": "Idempotency-Key was already used for a different message",
        "data": {
            "session_id": str(session_id),
            "task_id": redis.rpushed[0][1],
            "conflict_field": "message",
            "requested_value": "second",
            "existing_value": "first",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert len(redis.rpushed) == 1


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
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
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
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
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
        with pytest.raises(AppError) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "user.tool_confirmation",
            )
        )
    ).scalar_one()
    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SESSION_TOOL_CONFIRMATION_DELIVERY_FAILED",
        "message": "Failed to deliver tool confirmation",
        "data": {
            "session_id": str(session_id),
            "event_id": str(event.id),
            "event_type": "user.tool_confirmation",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

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
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
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
        with pytest.raises(AppError) as exc_info:
            await send_event(req, session_id, db_session, auth_ctx)
    finally:
        await engine.dispose()

    event = (
        await db_session.execute(
            select(JoySafeterSessionEvent).where(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.event_type == "user.interrupt",
            )
        )
    ).scalar_one()
    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SESSION_INTERRUPT_DELIVERY_FAILED",
        "message": "Failed to deliver interrupt",
        "data": {
            "session_id": str(session_id),
            "event_id": str(event.id),
            "event_type": "user.interrupt",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert [payload["type"] for _channel, payload in redis.published] == ["input", "cancel"]

    assert event.processed_at is not None, "the input half was delivered and should not be replayed as pending"


@pytest.mark.asyncio
async def test_stop_session_does_not_mark_idle_when_task_cancel_write_fails(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

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

    with pytest.raises(AppError) as exc_info:
        await stop_session(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SESSION_STOP_CANCEL_TASKS_FAILED",
        "message": "Failed to cancel all active tasks",
        "data": {"session_id": str(session_id), "active_task_ids": [str(task_id)]},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

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
async def test_stop_session_rejects_archived_session_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"stop-archived-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle", archived_at=utc_now())
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

    with pytest.raises(AppError) as exc_info:
        await stop_session(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ARCHIVED",
        "message": "Session is archived",
        "data": {"session_id": str(session_id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_stop_session_rejects_terminated_session_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"stop-terminated-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="terminated")
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

    with pytest.raises(AppError) as exc_info:
        await stop_session(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_TERMINATED",
        "message": "Session is terminated",
        "data": {"session_id": str(session_id), "session_status": "terminated"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_stop_session_marks_idle_only_after_active_tasks_cancelled(
    db_session,
    monkeypatch,
):
    redis = _FakeCommandRedis()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"stop-ok-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        chat_session_id=session_id,
        external_id="sandbox-stop-relay",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    db_session.add(sandbox)
    await db_session.flush()
    session.last_sandbox_id = sandbox.id
    sandbox_id = str(sandbox.id)

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session_id,
        sandbox_id=sandbox.id,
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
    command_publishes = [(channel, payload) for channel, payload in redis.published if channel.startswith("joysafeter:cmd:")]
    assert len(command_publishes) == 1
    channel, payload = command_publishes[0]
    assert channel == "joysafeter:cmd:owner-1"
    assert payload["type"] == "cancel"
    assert payload["sandbox_id"] == sandbox_id
    assert payload["reason"] == "Cancelled via session stop"


@pytest.mark.asyncio
async def test_delete_session_rejects_running_session_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"delete-running-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
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

    with pytest.raises(AppError) as exc_info:
        await delete_session_endpoint(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Running session cannot be deleted. Send user.interrupt first.",
        "data": {"session_id": str(session_id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "interrupt",
    }


@pytest.mark.asyncio
async def test_delete_session_rejects_active_task_before_deleted_broadcast(db_session, monkeypatch):
    broadcaster = _FakeBroadcaster()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: broadcaster)

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

    with pytest.raises(AppError) as exc_info:
        await delete_session_endpoint(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ACTIVE_TASK",
        "message": "Session has an active task; stop it before deleting session",
        "data": {"session_id": str(session_id), "active_task_ids": [str(task_id)]},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert broadcaster.sent == []

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert session_row.status == "idle"
    assert task_row.chat_session_id == session_id


@pytest.mark.asyncio
async def test_delete_session_relays_sandbox_destroy_to_rust_when_api_has_no_provider(db_session, monkeypatch):
    broadcaster = _FakeBroadcaster()
    redis = _FakeCommandRedis()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: broadcaster)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"delete-sandbox-rust-relay-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id
    external_id = sandbox.external_id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    response = await delete_session_endpoint(session_id, db_session, auth_ctx)

    assert response == {"id": f"sess_{session_id}", "object": "session", "deleted": True}
    assert len(redis.published) == 1
    channel, payload = redis.published[0]
    assert channel == "joysafeter:cmd:owner-1"
    assert payload["type"] == "destroy"
    assert payload["sandbox_id"] == str(sandbox_id)
    assert payload["external_id"] == external_id
    assert payload["reason"] == "session deleted"
    assert payload["ack_key"].startswith("joysafeter:cmd_ack:")
    assert redis.blpop_timeouts == [30]

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one_or_none()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert session_row is None
    assert sandbox_row.status == "destroyed"


@pytest.mark.asyncio
async def test_delete_session_keeps_session_when_rust_destroy_relay_unavailable(db_session, monkeypatch):
    broadcaster = _FakeBroadcaster()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: broadcaster)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"delete-sandbox-rust-relay-missing-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    auth_ctx = JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )

    with pytest.raises(AppError) as exc_info:
        await delete_session_endpoint(session_id, db_session, auth_ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SESSION_SANDBOX_DESTROY_FAILED",
        "message": "Session could not be deleted because its sandbox cleanup failed.",
        "data": {"session_id": str(session_id), "sandbox_id": str(sandbox_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert session_row.status == "idle"
    assert sandbox_row.status == "idle"
