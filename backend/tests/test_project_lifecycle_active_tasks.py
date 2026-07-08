import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import archive_project, set_default_project
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _admin_ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


class _FakeCommandRedis:
    def __init__(self, *, receivers: int = 1):
        self.receivers = receivers
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        if key.startswith("joysafeter:sandbox_owner:"):
            return "owner-1"
        return None

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        ack_key = payload.get("ack_key")
        if self.receivers > 0 and ack_key:
            self.acks[ack_key] = json.dumps({"command_id": payload.get("command_id"), "ok": True})
        return self.receivers

    async def blpop(self, key: str, timeout: int = 0):
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


@pytest.mark.asyncio
async def test_archive_project_rejects_active_tasks(db_session):
    org_id = f"org-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Launch Org", slug=f"launch-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="Launch", slug=f"launch-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    agent = JoySafeterAgent(name=f"project-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    project_id = project.id

    task = JoySafeterTask(
        agent_id=agent.id,
        project_id=project_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ACTIVE_TASKS",
        "message": "Project has active tasks. Stop or wait for them before archiving.",
        "data": {"project_id": project_id, "active": 1},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project_row.archived_at is None


@pytest.mark.asyncio
async def test_set_default_project_rejects_archived_project(db_session):
    org_id = f"org-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Default Org", slug=f"default-org-{uuid.uuid4()}")
    active_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Active",
        slug=f"active-{uuid.uuid4()}",
        is_default=True,
    )
    archived_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Archived",
        slug=f"archived-{uuid.uuid4()}",
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_project, archived_project])
    await db_session.commit()
    active_project_id = active_project.id
    archived_project_id = archived_project.id

    with pytest.raises(AppError) as exc_info:
        await set_default_project(archived_project_id, db_session, _admin_ctx(active_project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "Cannot set an archived project as default",
        "data": {"project_id": archived_project_id, "organization_id": org_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_project_id))).scalar_one()
    archived_row = (await db_session.execute(select(Project).where(Project.id == archived_project_id))).scalar_one()
    assert active_row.is_default is True
    assert archived_row.is_default is False


@pytest.mark.asyncio
async def test_archive_project_closes_session_sandbox_after_shutdown_ack_without_provider(db_session, monkeypatch):
    org_id = f"org-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Project Archive Org", slug=f"archive-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="Archive", slug=f"archive-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    project_id = project.id

    agent = JoySafeterAgent(name=f"project-archive-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, project_id=project_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        project_id=project_id,
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _FakeCommandRedis()
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_sandbox_provider", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    response = await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert response == {"status": "archived"}
    assert len(redis.published) == 1
    assert redis.published[0][1]["type"] == "shutdown"

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert project_row.archived_at is not None
    assert session_row.archived_at is not None
    assert session_row.status == "terminated"
    assert sandbox_row.status == "destroyed"
    assert sandbox_row.destroyed_at is not None


@pytest.mark.asyncio
async def test_archive_project_requires_session_sandbox_shutdown_ack_without_provider(db_session, monkeypatch):
    org_id = f"org-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Project Shutdown Org", slug=f"shutdown-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="Shutdown", slug=f"shutdown-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    project_id = project.id

    agent = JoySafeterAgent(name=f"project-shutdown-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, project_id=project_id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    session_id = session.id

    sandbox = JoySafeterSandbox(
        project_id=project_id,
        chat_session_id=session_id,
        external_id=f"sandbox-{uuid.uuid4()}",
        image="test-image",
        status="idle",
    )
    db_session.add(sandbox)
    await db_session.commit()
    await db_session.refresh(sandbox)
    sandbox_id = sandbox.id

    redis = _FakeCommandRedis(receivers=0)
    monkeypatch.setattr("app.joysafeter_shared.orchestrator_bridge.get_sandbox_provider", lambda: None)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "PROJECT_ARCHIVE_REDIS_SHUTDOWN_FAILED",
        "message": "Failed to deliver shutdown command to project session sandbox runtime.",
        "data": {"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }
    assert len(redis.published) == 1
    assert redis.published[0][1]["type"] == "shutdown"

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    session_row = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))
    ).scalar_one()
    sandbox_row = (
        await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one()
    assert project_row.archived_at is None
    assert session_row.archived_at is None
    assert session_row.status == "idle"
    assert sandbox_row.status == "idle"
    assert sandbox_row.destroyed_at is None
