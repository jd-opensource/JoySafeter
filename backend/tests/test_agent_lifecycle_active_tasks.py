import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select, text

from app.joysafeter_api.api.v1.agents import archive_agent, delete_agent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_agent import JoySafeterCreateAgentRequest
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import SandboxId, as_uuid
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _ensure_project(db_session, project_id: str) -> None:
    if await db_session.get(Project, project_id):
        return
    org = await db_session.get(Organization, "test-org")
    if not org:
        org = Organization(id="test-org", name="Test Org", slug="test-org")
        db_session.add(org)
    db_session.add(
        Project(
            id=project_id,
            org_id="test-org",
            name=project_id,
            slug=project_id,
            is_default=False,
        )
    )
    await db_session.commit()


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


class _ExternalIdChangingDestroyAckRedis(_FakeCommandRedis):
    def __init__(self, db_session, sandbox_id: SandboxId, new_external_id: str):
        super().__init__()
        self.db_session = db_session
        self.sandbox_id = sandbox_id
        self.new_external_id = new_external_id
        self.changed = False

    async def blpop(self, key: str, timeout: int = 0):
        if not self.changed:
            await self.db_session.execute(
                text(
                    "UPDATE joysafeter_sandboxes "
                    "SET external_id = :external_id, updated_at = NOW() "
                    "WHERE id = :sandbox_id"
                ),
                {"external_id": self.new_external_id, "sandbox_id": as_uuid(self.sandbox_id)},
            )
            await self.db_session.commit()
            self.changed = True
        return await super().blpop(key, timeout=timeout)


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
async def test_create_agent_allows_same_active_name_in_different_projects(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    name = f"scoped-agent-{uuid.uuid4()}"
    svc = JoySafeterAgentService(db_session)

    agent_a = await svc.create_agent(JoySafeterCreateAgentRequest(name=name), project_id="project-a")
    agent_b = await svc.create_agent(JoySafeterCreateAgentRequest(name=name), project_id="project-b")

    assert agent_a.id != agent_b.id
    assert agent_a.project_id == "project-a"
    assert agent_b.project_id == "project-b"


@pytest.mark.asyncio
async def test_create_agent_reuses_soft_deleted_name_without_purging_history(db_session):
    await _ensure_project(db_session, "project-a")
    name = f"reused-agent-{uuid.uuid4()}"
    svc = JoySafeterAgentService(db_session)
    old_agent = await svc.create_agent(JoySafeterCreateAgentRequest(name=name), project_id="project-a")
    old_agent_id = old_agent.id
    old_agent.deleted_at = utc_now()
    await db_session.commit()

    new_agent = await svc.create_agent(JoySafeterCreateAgentRequest(name=name), project_id="project-a")

    assert new_agent.id != old_agent_id
    db_session.expire_all()
    old_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == old_agent_id))).scalar_one()
    assert old_row.deleted_at is not None


@pytest.mark.asyncio
async def test_hard_delete_agent_rejects_cross_project_at_service_boundary(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    agent = JoySafeterAgent(name=f"cross-project-agent-{uuid.uuid4()}", project_id="project-b")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id

    deleted = await JoySafeterAgentService(db_session).hard_delete_agent(agent_id, project_id="project-a")

    assert deleted is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.project_id == "project-b"


@pytest.mark.asyncio
async def test_agent_child_resources_reject_cross_project_at_service_boundary(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    svc = JoySafeterAgentService(db_session)

    await svc.create_agent(
        JoySafeterCreateAgentRequest(name=f"project-a-agent-{uuid.uuid4()}"),
        project_id="project-a",
    )
    agent_b = await svc.create_agent(
        JoySafeterCreateAgentRequest(name=f"project-b-agent-{uuid.uuid4()}"),
        project_id="project-b",
    )
    agent_b_id = agent_b.id

    session_b = JoySafeterSession(agent_id=agent_b_id, project_id="project-b", status="idle")
    db_session.add(session_b)
    await db_session.commit()
    await db_session.refresh(session_b)
    session_b_id = session_b.id
    task_b = JoySafeterTask(
        agent_id=agent_b_id,
        chat_session_id=session_b_id,
        project_id="project-b",
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task_b)
    await db_session.commit()
    await db_session.refresh(task_b)
    task_b_id = task_b.id

    versions, has_more = await svc.list_versions(agent_b_id, project_id="project-a")
    snapshot = await svc.get_agent_version_snapshot(agent_b_id, 1, project_id="project-a")
    active_tasks = await svc.list_active_tasks_for_agent(agent_b_id, project_id="project-a")
    archived_session_ids = await svc.archive_sessions_for_agent(agent_b_id, project_id="project-a")

    assert versions == []
    assert has_more is False
    assert snapshot is None
    assert active_tasks == []
    assert archived_session_ids == []

    db_session.expire_all()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_b_id))
    ).scalar_one()
    assert session_row.project_id == "project-b"
    assert session_row.archived_at is None
    assert session_row.status == "idle"

    project_b_tasks = await svc.list_active_tasks_for_agent(agent_b_id, project_id="project-b")
    project_b_snapshot = await svc.get_agent_version_snapshot(agent_b_id, 1, project_id="project-b")
    assert [task.id for task in project_b_tasks] == [task_b_id]
    assert project_b_snapshot is not None


@pytest.mark.asyncio
async def test_agent_sandbox_children_use_parent_session_project_boundary(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    agent_b = JoySafeterAgent(name=f"sandbox-boundary-agent-{uuid.uuid4()}", project_id="project-b")
    db_session.add(agent_b)
    await db_session.commit()
    await db_session.refresh(agent_b)
    agent_b_id = agent_b.id

    session_b = JoySafeterSession(agent_id=agent_b_id, project_id="project-b", status="idle")
    db_session.add(session_b)
    await db_session.commit()
    await db_session.refresh(session_b)
    session_b_id = session_b.id

    sandbox_b = JoySafeterSandbox(
        chat_session_id=session_b_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox_b)
    await db_session.commit()
    await db_session.refresh(sandbox_b)
    sandbox_b_id = sandbox_b.id

    sandbox_svc = SandboxService(db_session)

    assert await sandbox_svc.find_by_session(session_b_id, project_id="project-a") is None
    assert await sandbox_svc.list_active_for_agent(agent_b_id, project_id="project-a") == []

    project_b_sandbox = await sandbox_svc.find_by_session(session_b_id, project_id="project-b")
    project_b_sandboxes = await sandbox_svc.list_active_for_agent(agent_b_id, project_id="project-b")
    assert project_b_sandbox is not None
    assert str(project_b_sandbox.id) == str(sandbox_b_id)
    assert [str(sandbox.id) for sandbox in project_b_sandboxes] == [str(sandbox_b_id)]


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
async def test_archive_agent_fails_closed_when_task_appears_after_active_check(db_session, monkeypatch):
    agent = JoySafeterAgent(name=f"archive-race-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    agent_id = agent.id
    session_id = session.id

    async def active_task_appears_after_check(self, agent_id, project_id=None):
        task = JoySafeterTask(
            agent_id=agent_id,
            chat_session_id=session_id,
            prompt="late task",
            status=JoySafeterTaskStatus.PENDING.value,
        )
        self.db.add(task)
        await self.db.commit()
        return 0

    monkeypatch.setattr(
        JoySafeterAgentService,
        "_count_active_tasks_for_agent",
        active_task_appears_after_check,
    )

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
    task_count = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.chat_session_id == session_id)))
        .scalars()
        .all()
    )
    assert agent_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"
    assert len(task_count) == 1


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
    assert payload["sandbox_id"] == str(as_uuid(sandbox_id))
    assert redis.blpop_timeouts == [30]

    db_session.expire_all()
    agent_row = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
    ).scalar_one_or_none()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is None
    assert sandbox_row.status == "destroyed"


@pytest.mark.asyncio
async def test_delete_agent_rejects_destroy_ack_if_sandbox_external_id_changed(db_session, monkeypatch):
    agent = JoySafeterAgent(name=f"stale-destroy-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id

    session = JoySafeterSession(agent_id=agent_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    old_external_id = f"sandbox-old-{uuid.uuid4()}"
    new_external_id = f"sandbox-new-{uuid.uuid4()}"
    sandbox = JoySafeterSandbox(
        chat_session_id=session.id,
        external_id=old_external_id,
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _ExternalIdChangingDestroyAckRedis(db_session, sandbox_id, new_external_id)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await delete_agent(agent_id, False, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "AGENT_SANDBOX_STATE_SYNC_FAILED",
        "message": "Agent could not be deleted because sandbox state sync failed.",
        "data": {"agent_id": str(agent_id), "sandbox_id": str(sandbox_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    assert redis.published[0][1]["external_id"] == old_external_id

    db_session.expire_all()
    agent_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert agent_row is not None
    assert sandbox_row.status == "idle"
    assert sandbox_row.external_id == new_external_id
    assert sandbox_row.destroyed_at is None


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
        "data": {
            "agent_id": str(agent_id),
            "task_id": str(task_id),
            "sandbox_id": str(sandbox_id),
        },
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

    command_types = [payload["type"] for channel, payload in redis.published if channel.startswith("joysafeter:cmd:")]
    assert command_types == ["cancel", "destroy"]
    assert redis.blpop_timeouts == [2, 30]

    db_session.expire_all()
    agent_row = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
    ).scalar_one_or_none()
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

    async def hide_active_tasks_once(self, agent_id, project_id=None):
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
