"""Direct task API dispatch must work in split-service mode and fail explicitly."""

import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select, text

from app.joysafeter_api.api.v1.environments import archive_environment
from app.joysafeter_api.api.v1.tasks import cancel_task, create_task
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import SandboxId, SessionId, TaskId, as_uuid
from app.joysafeter_shared.utils.datetime import utc_now


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


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
            self.acks[payload["ack_key"]] = json.dumps(
                {
                    "command_id": payload.get("command_id", ""),
                    "ok": True,
                }
            )
        return self.cancel_receivers

    async def blpop(self, key: str, timeout: int = 0):
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


class _TaskSandboxChangingAckRedis(_FakeCommandRedis):
    def __init__(
        self,
        db_session,
        task_id: TaskId,
        *,
        old_sandbox_id: SandboxId,
        new_sandbox_id: SandboxId,
        session_id: SessionId,
    ):
        super().__init__()
        self.db_session = db_session
        self.task_id = task_id
        self.old_sandbox_id = old_sandbox_id
        self.new_sandbox_id = new_sandbox_id
        self.session_id = session_id
        self.changed = False

    async def blpop(self, key: str, timeout: int = 0):
        if not self.changed:
            await self.db_session.execute(
                text(
                    "UPDATE joysafeter_sandboxes "
                    "SET status = 'destroyed', destroyed_at = NOW(), updated_at = NOW() "
                    "WHERE id = :old_sandbox_id"
                ),
                {"old_sandbox_id": as_uuid(self.old_sandbox_id)},
            )
            await self.db_session.execute(
                text(
                    "UPDATE joysafeter_sandboxes "
                    "SET chat_session_id = :session_id, status = 'running', updated_at = NOW() "
                    "WHERE id = :new_sandbox_id"
                ),
                {"new_sandbox_id": as_uuid(self.new_sandbox_id), "session_id": as_uuid(self.session_id)},
            )
            await self.db_session.execute(
                text(
                    "UPDATE joysafeter_tasks "
                    "SET sandbox_id = :sandbox_id, owner_epoch = COALESCE(owner_epoch, 0) + 1, updated_at = NOW() "
                    "WHERE id = :task_id"
                ),
                {"sandbox_id": as_uuid(self.new_sandbox_id), "task_id": as_uuid(self.task_id)},
            )
            await self.db_session.commit()
            self.changed = True
        return await super().blpop(key, timeout=timeout)


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


def _project_auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _service_auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
        principal_type="api_key",
    )


async def _create_project(db_session) -> Project:
    org = Organization(name=f"task-api-org-{uuid.uuid4()}", slug=f"task-api-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"task-api-project-{uuid.uuid4()}", slug=f"task-api-project-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_create_task_enqueues_via_redis_without_local_scheduler(db_session, monkeypatch):
    redis = _FakeRedis()
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
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id.uuid))]

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
        ("user.message", {"content": [{"type": "text", "text": "scan target"}], "task_id": str(task.id)}),
        ("session.status_running", {"task_id": str(task.id)}),
    ]


@pytest.mark.asyncio
async def test_create_task_auto_session_stores_execution_snapshot(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    env = JoySafeterEnvironment(
        name=f"task-snapshot-env-{uuid.uuid4()}",
        description="",
        config={"env_vars": {"SUBMITTED_ENV": "1"}},
        image_tag="submitted-image:1",
        image_version=1,
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    env_ref = str(env.id)
    agent = JoySafeterAgent(
        name=f"task-snapshot-agent-{uuid.uuid4()}",
        version=1,
        environment_ref=env_ref,
        env={"SUBMITTED_AGENT": "1"},
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    response = await create_task(
        JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target"),
        db_session,
        _auth_ctx(),
    )

    env.config = {"env_vars": {"LIVE_ENV": "2"}}
    env.image_tag = "live-image:2"
    env.image_version = 2
    agent.env = {"LIVE_AGENT": "2"}
    agent.version = 2
    await db_session.commit()

    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == response.id))).scalar_one()
    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == task.chat_session_id))
    ).scalar_one()

    assert session.environment_ref == env_ref
    assert session.agent_version == 1
    assert session.agent_snapshot["environment_ref"] == env_ref
    assert session.agent_snapshot["env"] == {"SUBMITTED_AGENT": "1"}
    assert session.agent_snapshot["environment"]["image_tag"] == "submitted-image:1"
    assert session.agent_snapshot["environment"]["config"]["env_vars"] == {"SUBMITTED_ENV": "1"}


@pytest.mark.asyncio
async def test_create_task_rejects_missing_environment_ref_with_structured_error(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-missing-env-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    missing_ref = f"missing-env-{uuid.uuid4()}"
    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target", environment_ref=missing_ref)
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "TASK_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert redis.rpushed == []
    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    assert task_count == 0


@pytest.mark.asyncio
async def test_create_task_rejects_archived_environment_ref_with_structured_error(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    env = JoySafeterEnvironment(
        name=f"archived-task-env-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    agent = JoySafeterAgent(name=f"direct-task-archived-env-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    env_ref = str(env.id)
    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target", environment_ref=env_ref)
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {env_ref}",
        "data": {"environment_ref": env_ref, "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert redis.rpushed == []
    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    assert task_count == 0


@pytest.mark.asyncio
async def test_create_task_rejects_archived_agent_with_structured_error(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-archived-agent-{uuid.uuid4()}", archived_at=utc_now())
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new tasks.",
        "data": {"agent_id": str(agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert redis.rpushed == []
    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    session_count = await db_session.scalar(select(func.count()).select_from(JoySafeterSession))
    assert task_count == 0
    assert session_count == 0


@pytest.mark.asyncio
async def test_create_task_enqueue_failure_returns_503_and_marks_task_failed(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: None),
    )

    agent = JoySafeterAgent(name=f"direct-task-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")

    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    task = (await db_session.execute(select(JoySafeterTask))).scalar_one()
    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"task_id": str(task.id), "session_id": str(task.chat_session_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

    assert task.status == JoySafeterTaskStatus.FAILED.value
    assert "Failed to enqueue task" in (task.error or "")

    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == task.chat_session_id))
    ).scalar_one()
    assert session.status == "idle"
    expected_stop_reason = {
        "type": "error",
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"task_id": str(task.id), "session_id": str(task.chat_session_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert session.stop_reason == expected_stop_reason

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
        ("user.message", {"content": [{"type": "text", "text": "scan target"}], "task_id": str(task.id)}),
        ("session.status_running", {"task_id": str(task.id)}),
        (
            "session.status_idle",
            {
                "task_id": str(task.id),
                "stop_reason": expected_stop_reason,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_create_task_rejects_session_with_active_task_even_if_session_looks_idle(db_session, monkeypatch):
    redis = _FakeRedis()
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
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ACTIVE_TASK",
        "message": "Session has an active task; wait for completion before creating a new task",
        "data": {
            "session_id": str(session.id),
            "active_task_ids": [str(existing_task.id)],
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.rpushed == []
    tasks = (await db_session.execute(select(JoySafeterTask).order_by(JoySafeterTask.created_at.asc()))).scalars().all()
    assert [task.id for task in tasks] == [existing_task.id]


@pytest.mark.asyncio
async def test_create_task_with_existing_session_marks_running_before_enqueue(db_session, monkeypatch):
    redis = _FakeRedis()
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
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id.uuid))]

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
        ("user.message", {"content": [{"type": "text", "text": "scan target"}], "task_id": str(response.id)}),
        ("session.status_running", {"task_id": str(response.id)}),
    ]


@pytest.mark.asyncio
async def test_create_task_rejects_environment_ref_mismatch_for_existing_session(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    session_env = JoySafeterEnvironment(name=f"session-env-{uuid.uuid4()}", description="")
    requested_env = JoySafeterEnvironment(name=f"requested-env-{uuid.uuid4()}", description="")
    db_session.add(session_env)
    await db_session.commit()
    await db_session.refresh(session_env)
    db_session.add(requested_env)
    await db_session.commit()
    await db_session.refresh(requested_env)

    agent = JoySafeterAgent(name=f"direct-task-env-mismatch-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=str(session_env.id))
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    req = JoySafeterCreateTaskRequest(
        agent_id=agent.id,
        chat_session_id=session.id,
        environment_ref=str(requested_env.id),
        prompt="scan target",
    )

    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TASK_SESSION_ENVIRONMENT_MISMATCH",
        "message": "Task environment_ref does not match the existing session environment",
        "data": {
            "session_id": str(session.id),
            "requested_environment_ref": str(requested_env.id),
            "session_environment_ref": str(session_env.id),
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    assert redis.rpushed == []
    task_count = await db_session.scalar(select(func.count()).select_from(JoySafeterTask))
    assert task_count == 0


@pytest.mark.asyncio
async def test_create_task_uses_existing_session_environment_before_agent_default(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    session_env = JoySafeterEnvironment(name=f"session-env-{uuid.uuid4()}", description="")
    db_session.add(session_env)
    await db_session.commit()
    await db_session.refresh(session_env)

    missing_agent_env = f"missing-agent-env-{uuid.uuid4()}"
    agent = JoySafeterAgent(
        name=f"direct-task-session-env-agent-{uuid.uuid4()}",
        environment_ref=missing_agent_env,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=str(session_env.id))
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session.id, prompt="scan target")

    response = await create_task(req, db_session, _auth_ctx())

    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == response.id))).scalar_one()
    assert task.chat_session_id == session.id
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id.uuid))]


@pytest.mark.asyncio
async def test_create_task_idempotent_retry_after_enqueue_failure_stays_503(db_session, monkeypatch):
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

    with pytest.raises(AppError) as first_exc:
        await create_task(req, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(AppError) as second_exc:
        await create_task(req, db_session, _auth_ctx(), idempotency_key=key)

    assert (await handled_app_error_payload(first_exc.value, status_code=503))["code"] == "TASK_ENQUEUE_FAILED"

    tasks = (await db_session.execute(select(JoySafeterTask))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].status == JoySafeterTaskStatus.FAILED.value
    assert await handled_app_error_payload(second_exc.value, status_code=503) == {
        "code": "TASK_ENQUEUE_FAILED",
        "message": "Failed to enqueue task",
        "data": {"task_id": str(tasks[0].id), "session_id": str(tasks[0].chat_session_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_create_task_idempotent_race_does_not_duplicate_enqueue_or_leave_orphan_session(
    db_session,
    monkeypatch,
):
    redis = _FakeRedis()
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

    first_response = await create_task(first, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(AppError) as exc_info:
        await create_task(second, db_session, _auth_ctx(), idempotency_key=key)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TASK_IDEMPOTENCY_KEY_MISMATCH",
        "message": "Idempotency-Key was already used for a different prompt",
        "data": {
            "task_id": str(first_response.id),
            "conflict_field": "prompt",
            "requested_value": "scan target b",
            "existing_value": "scan target a",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_task_rejects_idempotency_key_reuse_for_different_session(db_session, monkeypatch):
    redis = _FakeRedis()
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

    first_response = await create_task(first, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(AppError) as exc_info:
        await create_task(second, db_session, _auth_ctx(), idempotency_key=key)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TASK_IDEMPOTENCY_KEY_MISMATCH",
        "message": "Idempotency-Key was already used for a different session",
        "data": {
            "task_id": str(first_response.id),
            "conflict_field": "chat_session_id",
            "requested_value": str(session_b.id),
            "existing_value": str(session_a.id),
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_task_idempotent_replay_accepts_same_session_uuid_value_across_uuid_types(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"direct-task-idem-same-session-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    key = f"task-replay-same-session-{uuid.uuid4()}"
    request = JoySafeterCreateTaskRequest(agent_id=agent.id, chat_session_id=session_id, prompt="scan target")

    first = await create_task(request, db_session, _auth_ctx(), idempotency_key=key)
    db_session.expire_all()
    second = await create_task(request, db_session, _auth_ctx(), idempotency_key=key)

    assert second.id == first.id
    assert second.status == first.status
    assert redis.rpushed == [("joysafeter:global_queue", str(first.id.uuid))]


@pytest.mark.asyncio
async def test_create_task_rejects_idempotency_key_reuse_for_different_environment(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    env_a = JoySafeterEnvironment(name=f"idem-env-a-{uuid.uuid4()}", description="")
    db_session.add(env_a)
    await db_session.commit()
    await db_session.refresh(env_a)
    env_b = JoySafeterEnvironment(name=f"idem-env-b-{uuid.uuid4()}", description="")
    db_session.add(env_b)
    await db_session.commit()
    await db_session.refresh(env_b)

    agent = JoySafeterAgent(name=f"direct-task-idem-env-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    key = f"task-reuse-env-{uuid.uuid4()}"
    first = JoySafeterCreateTaskRequest(
        agent_id=agent.id,
        environment_ref=str(env_a.id),
        prompt="scan target",
    )
    second = JoySafeterCreateTaskRequest(
        agent_id=agent.id,
        environment_ref=str(env_b.id),
        prompt="scan target",
    )

    first_response = await create_task(first, db_session, _auth_ctx(), idempotency_key=key)
    with pytest.raises(AppError) as exc_info:
        await create_task(second, db_session, _auth_ctx(), idempotency_key=key)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TASK_IDEMPOTENCY_KEY_MISMATCH",
        "message": "Idempotency-Key was already used for a different environment",
        "data": {
            "task_id": str(first_response.id),
            "conflict_field": "environment_ref",
            "requested_value": str(env_b.id),
            "existing_value": str(env_a.id),
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_task_idempotent_retry_allows_original_environment_archived_later(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    env = JoySafeterEnvironment(name=f"idem-archived-env-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    agent = JoySafeterAgent(name=f"direct-task-idem-archived-env-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    env_ref = str(env.id)
    key = f"task-retry-archived-env-{uuid.uuid4()}"
    req = JoySafeterCreateTaskRequest(agent_id=agent.id, environment_ref=env_ref, prompt="scan target")

    first_response = await create_task(req, db_session, _auth_ctx(), idempotency_key=key)
    task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == first_response.id))).scalar_one()
    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == task.chat_session_id))
    ).scalar_one()
    task.status = JoySafeterTaskStatus.COMPLETED.value
    session.status = "terminated"
    session.archived_at = utc_now()
    await db_session.commit()

    await archive_environment(env.id, db_session, _auth_ctx())

    retry_response = await create_task(req, db_session, _auth_ctx(), idempotency_key=key)

    assert retry_response.id == first_response.id
    assert retry_response.status == JoySafeterTaskStatus.COMPLETED.value
    assert redis.rpushed == [("joysafeter:global_queue", str(first_response.id.uuid))]


@pytest.mark.asyncio
async def test_cancel_task_rejects_terminal_task_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"cancel-terminal-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="already done",
        status=JoySafeterTaskStatus.COMPLETED.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(AppError) as exc_info:
        await cancel_task(task.id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TASK_ALREADY_TERMINAL",
        "message": "Task already in terminal state: completed",
        "data": {
            "task_id": str(task.id),
            "task_status": "completed",
        },
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_cancel_task_relays_cancel_to_rust_orchestrator(db_session, monkeypatch):
    redis = _FakeCommandRedis()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"cancel-relay-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.flush()

    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id="sandbox-cancel-relay",
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
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
        owner_epoch=7,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id

    response = await cancel_task(task_id, db_session, _auth_ctx())

    assert response == {"id": str(task_id), "status": "cancelled"}
    command_publishes = [
        (channel, payload) for channel, payload in redis.published if channel.startswith("joysafeter:cmd:")
    ]
    assert len(command_publishes) == 1
    channel, payload = command_publishes[0]
    assert channel == "joysafeter:cmd:owner-1"
    assert payload["type"] == "cancel"
    assert payload["sandbox_id"] == str(as_uuid(sandbox.id))
    assert payload["reason"] == "Cancelled via API"
    assert payload["ack_key"].startswith("joysafeter:cmd_ack:")


@pytest.mark.asyncio
async def test_cancel_task_rejects_ack_if_task_moved_to_another_sandbox(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

    agent = JoySafeterAgent(name=f"cancel-stale-sandbox-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.flush()

    old_sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=f"sandbox-old-{uuid.uuid4()}",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    new_sandbox = JoySafeterSandbox(
        chat_session_id=None,
        external_id=f"sandbox-new-{uuid.uuid4()}",
        provider="docker",
        status="pooled",
        image="joysafeter/test:latest",
    )
    db_session.add(old_sandbox)
    await db_session.flush()
    db_session.add(new_sandbox)
    await db_session.flush()
    session.last_sandbox_id = old_sandbox.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        sandbox_id=old_sandbox.id,
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
        owner_epoch=7,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    old_sandbox_id = old_sandbox.id
    new_sandbox_id = new_sandbox.id
    session_id = session.id

    redis = _TaskSandboxChangingAckRedis(
        db_session,
        task_id,
        old_sandbox_id=old_sandbox_id,
        new_sandbox_id=new_sandbox_id,
        session_id=session_id,
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await cancel_task(task_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_CANCEL_STATE_SYNC_FAILED",
        "message": "Task cancel could not be finalized because task ownership changed.",
        "data": {
            "task_id": str(task_id),
            "session_id": str(session_id),
            "sandbox_id": str(old_sandbox_id),
        },
        "source": "api",
        "retryable": True,
        "user_action": "refresh",
    }

    command_publishes = [
        (channel, payload) for channel, payload in redis.published if channel.startswith("joysafeter:cmd:")
    ]
    assert len(command_publishes) == 1
    assert command_publishes[0][1]["sandbox_id"] == str(as_uuid(old_sandbox_id))

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert str(task_row.sandbox_id) == str(new_sandbox_id)
    assert task_row.owner_epoch == 8
    assert session_row.status == "running"


@pytest.mark.asyncio
async def test_cancel_task_does_not_mark_cancelled_when_runtime_cancel_relay_fails(db_session, monkeypatch):
    redis = _FakeCommandRedis(cancel_receivers=0)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    agent = JoySafeterAgent(name=f"cancel-relay-fail-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.flush()
    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id="sandbox-cancel-relay-fail",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    db_session.add(sandbox)
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        sandbox_id=sandbox.id,
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    session_id = session.id
    sandbox_id = sandbox.id

    with pytest.raises(AppError) as exc_info:
        await cancel_task(task_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_CANCEL_REDIS_RELAY_FAILED",
        "message": "Failed to cancel task in sandbox runtime.",
        "data": {
            "task_id": str(task_id),
            "session_id": str(session_id),
            "sandbox_id": str(sandbox_id),
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    command_publishes = [
        (channel, payload) for channel, payload in redis.published if channel.startswith("joysafeter:cmd:")
    ]
    assert len(command_publishes) == 1

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert session_row.status == "running"


@pytest.mark.asyncio
async def test_cancel_running_task_without_runtime_owner_fails_closed(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)

    agent = JoySafeterAgent(name=f"cancel-missing-owner-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        prompt="corrupt running task",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    session_id = session.id

    with pytest.raises(AppError) as exc_info:
        await cancel_task(task_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_CANCEL_STATE_SYNC_FAILED",
        "message": "Task cancel could not be finalized because task has no runtime owner.",
        "data": {"task_id": str(task_id), "session_id": str(session_id)},
        "source": "api",
        "retryable": True,
        "user_action": "refresh",
    }

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    assert task_row.status == JoySafeterTaskStatus.RUNNING.value
    assert task_row.sandbox_id is None
    assert session_row.status == "running"


@pytest.mark.asyncio
async def test_cancel_task_reports_session_idle_write_failure(db_session, monkeypatch):
    redis = _FakeCommandRedis()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    async def fail_idle_transition(self, session_id, status, task_id, stop_reason=None):
        raise RuntimeError("session write failed")

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_session_service.SessionService.update_session_status_for_task_event",
        fail_idle_transition,
    )

    agent = JoySafeterAgent(name=f"cancel-session-sync-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="running")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=f"sandbox-cancel-session-sync-{uuid.uuid4()}",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    session.last_sandbox_id = sandbox.id

    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        sandbox_id=sandbox.id,
        prompt="long running",
        status=JoySafeterTaskStatus.RUNNING.value,
        owner_epoch=7,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = task.id
    session_id = session.id

    with pytest.raises(AppError) as exc_info:
        await cancel_task(task_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "TASK_CANCEL_SESSION_SYNC_FAILED",
        "message": "Task was cancelled, but failed to mark the linked session idle.",
        "data": {"task_id": str(task_id), "session_id": str(session_id)},
        "source": "api",
        "retryable": True,
        "user_action": "refresh",
    }

    db_session.expire_all()
    task_row = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
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
    assert task_row.status == JoySafeterTaskStatus.CANCELLED.value
    assert session_row.status == "running"
    assert idle_events == 0


@pytest.mark.asyncio
async def test_per_user_admission_rejects_human_over_limit(db_session, monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    monkeypatch.setattr(settings, "max_concurrent_per_user", 1)

    agent = JoySafeterAgent(name=f"per-user-human-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    # One active task already attributed to the human principal.
    await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id, prompt="busy", user_id="test-user", org_id="test-org"
    )

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=429) == {
        "code": "USER_TASK_LIMIT_EXCEEDED",
        "message": "User has reached their concurrent task limit (1).",
        "data": {
            "limit": 1,
            "active": 1,
            "user_id": "test-user",
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.rpushed == [], "an admission-rejected task must not be enqueued"


@pytest.mark.asyncio
async def test_per_project_admission_returns_structured_retryable_error(db_session, monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    monkeypatch.setattr(settings, "max_concurrent_per_project", 1)

    project = await _create_project(db_session)
    agent = JoySafeterAgent(name=f"per-project-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id,
        prompt="busy",
        project_id=project.id,
        user_id="other-user",
        org_id="test-org",
    )

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _project_auth_ctx(project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=429) == {
        "code": "PROJECT_TASK_LIMIT_EXCEEDED",
        "message": "Project has reached its concurrent task limit (1).",
        "data": {
            "limit": 1,
            "active": 1,
            "project_id": project.id,
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.rpushed == [], "an admission-rejected task must not be enqueued"


@pytest.mark.asyncio
async def test_per_user_admission_skips_service_principal(db_session, monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    monkeypatch.setattr(settings, "max_concurrent_per_user", 1)

    agent = JoySafeterAgent(name=f"per-user-service-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    # Same identity already over the per-user limit, but the caller is a service
    # key: the per-user fairness quota must not apply to it.
    await JoySafeterTaskService(db_session).create_task(
        agent_id=agent.id, prompt="busy", user_id="test-user", org_id="test-org"
    )

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target")
    response = await create_task(req, db_session, _service_auth_ctx())

    assert response.status == JoySafeterTaskStatus.PENDING.value
    assert redis.rpushed == [("joysafeter:global_queue", str(response.id.uuid))]
