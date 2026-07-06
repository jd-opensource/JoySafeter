"""Direct task API dispatch must work in split-service mode and fail explicitly."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.tasks import create_task
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


@pytest.mark.asyncio
async def test_create_task_enqueues_via_redis_without_local_scheduler(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")

    response = await create_task(req, db_session, _auth_ctx())

    assert response.id is not None
    assert response.status == JoySafeterTaskStatus.PENDING.value
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id))]

    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == response.id))).scalar_one()
    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == task.chat_session_id))
    ).scalar_one()
    assert session.status == "running"

    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == task.chat_session_id)
                .order_by(JoySafeterSessionEvent.seq.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [(event.event_type, event.payload) for event in events] == [
        ("session.status_running", {"task_id": str(task.id)})
    ]


@pytest.mark.asyncio
async def test_create_task_enqueue_failure_returns_503_and_marks_task_failed(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"direct-task-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")

    with pytest.raises(HTTPException) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Failed to enqueue task"

    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert task.status == JoySafeterTaskStatus.FAILED.value
    assert "Failed to enqueue task" in (task.error or "")

    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == task.chat_session_id))
    ).scalar_one()
    assert session.status == "idle"
    assert session.stop_reason == {"type": "error", "message": "Failed to enqueue task"}

    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == task.chat_session_id)
                .order_by(JoySafeterSessionEvent.seq.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [(event.event_type, event.payload) for event in events] == [
        ("session.status_running", {"task_id": str(task.id)}),
        (
            "session.status_idle",
            {
                "task_id": str(task.id),
                "stop_reason": {"type": "error", "message": "Failed to enqueue task"},
            },
        ),
    ]


@pytest.mark.asyncio
async def test_create_task_rejects_session_with_active_task_even_if_session_looks_idle(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-active-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    existing_task = await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id,
        prompt="already running",
        chat_session_id=session.id,
        user_id="test-user",
        org_id="test-org",
    )

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session.id, prompt="scan target")
    with pytest.raises(HTTPException) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Session has an active task; wait for completion before creating a new task"
    assert redis.rpushed == []
    tasks = (await db_session.execute(select(JoySafeterTask).order_by(JoySafeterTask.created_at.asc()))).scalars().all()
    assert [task.id for task in tasks] == [existing_task.id]


@pytest.mark.asyncio
async def test_create_task_with_existing_session_marks_running_before_enqueue(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-existing-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session.id, prompt="scan target")

    response = await create_task(req, db_session, _auth_ctx())

    await db_session.refresh(session)
    assert session.status == "running"
    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == response.id))).scalar_one()
    assert task.chat_session_id == session.id
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id))]

    events = (
        (
            await db_session.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == session.id)
                .order_by(JoySafeterSessionEvent.seq.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [(event.event_type, event.payload) for event in events] == [
        ("session.status_running", {"task_id": str(response.id)})
    ]


@pytest.mark.asyncio
async def test_create_task_idempotent_retry_after_enqueue_failure_stays_503(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"direct-task-idem-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    key = f"task-{uuid.uuid4()}"

    with pytest.raises(HTTPException) as first_exc:
        await create_task(req, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(HTTPException) as second_exc:
        await create_task(req, db_session, _auth_ctx(), idempotency_key=key)

    assert first_exc.value.status_code == 503
    assert second_exc.value.status_code == 503
    assert second_exc.value.detail == "Failed to enqueue task"

    tasks = (await db_session.execute(select(JoySafeterTask))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].status == JoySafeterTaskStatus.FAILED.value


@pytest.mark.asyncio
async def test_create_task_idempotent_race_does_not_duplicate_enqueue_or_leave_orphan_session(
    db_session,
    monkeypatch,
):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-race-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    existing_session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(existing_session)
    await db_session.commit()
    await db_session.refresh(existing_session)

    key = f"task-race-{uuid.uuid4()}"
    existing_task = await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id,
        prompt="scan target",
        chat_session_id=existing_session.id,
        idempotency_key=key,
        user_id="test-user",
        org_id="test-org",
    )

    original_get = JoySafeterTaskService.get_by_idempotency_key
    first_lookup = True

    async def hide_existing_once(self, idempotency_key, project_id=None):
        nonlocal first_lookup
        if first_lookup:
            first_lookup = False
            return None
        return await original_get(self, idempotency_key, project_id=project_id)

    monkeypatch.setattr(JoySafeterTaskService, "get_by_idempotency_key", hide_existing_once)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    response = await create_task(req, db_session, _auth_ctx(), idempotency_key=key)

    assert response.id == existing_task.id
    assert redis.rpushed == [], "idempotency conflict must not enqueue the existing task again"
    session_count = await db_session.scalar(select(func.count()).select_from(JoySafeterSession))
    assert session_count == 1, "the auto-created session from the losing race must be deleted"


@pytest.mark.asyncio
async def test_create_task_rejects_idempotency_key_reuse_for_different_prompt(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-idem-prompt-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    key = f"task-reuse-{uuid.uuid4()}"
    first = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target a")
    second = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target b")

    await create_task(first, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(HTTPException) as exc_info:
        await create_task(second, db_session, _auth_ctx(), idempotency_key=key)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Idempotency-Key was already used for a different prompt"


@pytest.mark.asyncio
async def test_create_task_rejects_idempotency_key_reuse_for_different_session(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.joysafeter_orchestrator.lifespan.get_scheduler", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-idem-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session_a = JoySafeterSession(agent_id=agent.id, status="idle")
    session_b = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session_a)
    await db_session.flush()
    db_session.add(session_b)
    await db_session.commit()
    await db_session.refresh(session_a)
    await db_session.refresh(session_b)

    key = f"task-reuse-session-{uuid.uuid4()}"
    first = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session_a.id, prompt="scan target")
    second = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session_b.id, prompt="scan target")

    await create_task(first, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(HTTPException) as exc_info:
        await create_task(second, db_session, _auth_ctx(), idempotency_key=key)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Idempotency-Key was already used for a different session"
