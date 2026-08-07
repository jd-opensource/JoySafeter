import json
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.environments import (
    archive_environment,
    create_environment,
    delete_environment,
    update_environment,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    Packages,
    UpdateEnvironmentRequest,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import as_uuid
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


class _FakeRuntimeRedis:
    def __init__(
        self,
        *,
        instance_ids: list[str] | None = None,
        image_tag: str | None = "joysafeter/env-test:v1",
        ok: bool = True,
        code: str | None = None,
        error: str | None = None,
    ):
        self.instance_ids = instance_ids if instance_ids is not None else ["runtime-1"]
        self.image_tag = image_tag
        self.ok = ok
        self.code = code
        self.error = error
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}
        self.blpop_timeouts: list[int] = []

    async def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None):
        assert match == "joysafeter:instances:*"
        if cursor != 0:
            return 0, []
        return 0, [f"joysafeter:instances:{instance_id}" for instance_id in self.instance_ids]

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        ack_key = payload.get("ack_key")
        if ack_key:
            ack_payload = {
                "command_id": payload.get("command_id"),
                "ok": self.ok,
                "image_tag": self.image_tag,
            }
            if self.code:
                ack_payload["code"] = self.code
            if self.error:
                ack_payload["error"] = self.error
            self.acks[ack_key] = json.dumps(ack_payload)
        return 1

    async def blpop(self, key: str, timeout: int = 0):
        self.blpop_timeouts.append(timeout)
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


@pytest.mark.asyncio
async def test_create_environment_allows_same_active_name_in_different_projects(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    name = f"scoped-env-{uuid.uuid4()}"
    svc = EnvironmentService(db_session)

    env_a = await svc.create_environment(CreateEnvironmentRequest(name=name), project_id="project-a")
    env_b = await svc.create_environment(CreateEnvironmentRequest(name=name), project_id="project-b")

    assert env_a.id != env_b.id
    assert env_a.project_id == "project-a"
    assert env_b.project_id == "project-b"


@pytest.mark.asyncio
async def test_create_environment_purges_only_same_project_soft_deleted_name(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    name = f"reused-env-{uuid.uuid4()}"
    stale_other_project = JoySafeterEnvironment(name=name, description="", project_id="project-b", deleted_at=utc_now())
    stale_same_project = JoySafeterEnvironment(name=name, description="", project_id="project-a", deleted_at=utc_now())
    db_session.add(stale_other_project)
    await db_session.commit()
    await db_session.refresh(stale_other_project)
    db_session.add(stale_same_project)
    await db_session.commit()
    await db_session.refresh(stale_same_project)
    stale_other_project_id = stale_other_project.id
    stale_same_project_id = stale_same_project.id

    created = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=name),
        project_id="project-a",
    )

    assert created.project_id == "project-a"
    db_session.expire_all()
    other_project_row = (
        await db_session.execute(
            select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == stale_other_project_id)
        )
    ).scalar_one()
    same_project_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == stale_same_project_id))
    ).scalar_one_or_none()
    assert other_project_row.deleted_at is not None
    assert same_project_row is None


@pytest.mark.asyncio
async def test_update_environment_rejects_cross_project_at_service_boundary(db_session):
    await _ensure_project(db_session, "project-a")
    await _ensure_project(db_session, "project-b")
    env = JoySafeterEnvironment(name=f"cross-project-env-{uuid.uuid4()}", description="", project_id="project-b")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    updated = await EnvironmentService(db_session).update_environment(
        env_id,
        UpdateEnvironmentRequest(description="changed"),
        project_id="project-a",
    )
    deleted = await EnvironmentService(db_session).delete_environment(env_id, project_id="project-a")
    archived = await EnvironmentService(db_session).archive_environment(env_id, project_id="project-a")

    assert updated is None
    assert deleted is False
    assert archived is False
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert row.description == ""
    assert row.deleted_at is None
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_create_environment_rejects_missing_secret_ref_with_structured_error(db_session):
    missing_ref = f"missing-secret-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(
        name=f"secret-ref-env-{uuid.uuid4()}", config=EnvironmentConfig(secret_refs=[missing_ref])
    )

    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ENVIRONMENT_SECRET_NOT_FOUND",
        "message": f"Secret not found: {missing_ref}",
        "data": {"secret_ref": missing_ref},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.name == req.name))
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_create_environment_with_packages_builds_image_via_rust_runtime(db_session, monkeypatch):
    redis = _FakeRuntimeRedis(image_tag="joysafeter/env-runtime:v1")
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    req = CreateEnvironmentRequest(
        name=f"runtime-build-env-{uuid.uuid4()}",
        config=EnvironmentConfig(packages=Packages(apt=["curl"], pip=["pytest"])),
    )

    response = await create_environment(req, db_session, _auth_ctx())

    assert response.image_tag == "joysafeter/env-runtime:v1"
    assert response.image_version == 1
    assert len(redis.published) == 1
    channel, payload = redis.published[0]
    assert channel == "joysafeter:cmd:runtime-1"
    assert payload["type"] == "build_environment_image"
    # Bare uuid: the Rust command_listener parses environment_id into a bare Uuid for
    # build_environment_image (physical command boundary), so no env_ prefix here.
    assert payload["environment_id"] == str(as_uuid(response.id))
    assert payload["version"] == 1
    assert payload["packages"] == {
        "apt": ["curl"],
        "pip": ["pytest"],
        "npm": [],
        "cargo": [],
        "gem": [],
        "go": [],
    }
    assert redis.blpop_timeouts == [600]


@pytest.mark.asyncio
async def test_create_environment_with_packages_rolls_back_when_rust_builder_unavailable(db_session, monkeypatch):
    redis = _FakeRuntimeRedis(instance_ids=[])
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    env_name = f"runtime-unavailable-env-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(
        name=env_name,
        config=EnvironmentConfig(packages=Packages(apt=["curl"])),
    )

    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    detail = await handled_app_error_payload(exc_info.value, status_code=503)
    assert detail["code"] == "ENVIRONMENT_IMAGE_BUILDER_UNAVAILABLE"
    assert detail["message"] == "Image builder is unavailable; cannot provision environment packages right now"
    assert detail["source"] == "runtime"
    assert detail["retryable"] is True
    assert detail["user_action"] == "retry"

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.name == env_name))
    ).scalar_one()
    assert env_row.deleted_at is not None


@pytest.mark.asyncio
async def test_archive_environment_rejects_non_archived_session_reference(db_session):
    env = JoySafeterEnvironment(name=f"env-ref-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=env.name)
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
        "message": "Environment is referenced by one or more active sessions.",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_archive_environment_rejects_canonical_id_session_reference(db_session):
    env = JoySafeterEnvironment(name=f"canonical-env-ref-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"canonical-env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=str(env.id))
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
        "message": "Environment is referenced by one or more active sessions.",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_environment_reference_resolver_requires_prefix_for_id_lookup(db_session):
    env = JoySafeterEnvironment(name=f"typed-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    service = EnvironmentService(db_session)

    assert await service.get_environment_by_ref(str(env.id)) == env
    assert await service.get_environment_by_ref(str(env.id.uuid)) is None
    assert await service.get_environment_by_ref(env.name) == env


@pytest.mark.asyncio
async def test_archive_environment_rejects_active_task_agent_reference_without_session(db_session):
    env = JoySafeterEnvironment(name=f"agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before archiving."
        ),
        "data": {"environment_id": str(env_id), "task_id": str(task.id), "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_environment_rejects_active_task_agent_reference_without_session(db_session):
    env = JoySafeterEnvironment(name=f"delete-agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"delete-env-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(AppError) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before deleting."
        ),
        "data": {"environment_id": str(env_id), "task_id": str(task.id), "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None


@pytest.mark.asyncio
async def test_delete_environment_rejects_agent_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"static-agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"static-env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    with pytest.raises(AppError) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_AGENT_REFERENCE",
        "message": f"Environment is referenced by agent '{agent.name}'.",
        "data": {"environment_id": str(env_id), "agent_name": agent.name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None


@pytest.mark.asyncio
async def test_archive_environment_rejects_cron_trigger_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"schedule-env-ref-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"schedule-env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    schedule = JoySafeterTrigger(
        name=f"env-schedule-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run later",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now(),
        environment_ref=str(env.id),
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(schedule)
    await db_session.commit()
    trigger_name = schedule.name

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_TRIGGER_REFERENCE",
        "message": f"Environment is referenced by cron trigger '{trigger_name}'.",
        "data": {"environment_id": str(env_id), "trigger_name": trigger_name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_environment_rejects_cron_trigger_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"delete-schedule-env-ref-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"delete-schedule-env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    schedule = JoySafeterTrigger(
        name=f"delete-env-schedule-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run later",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=False,
        next_run_at=None,
        environment_ref=env.name,
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(schedule)
    await db_session.commit()
    trigger_name = schedule.name

    with pytest.raises(AppError) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_TRIGGER_REFERENCE",
        "message": f"Environment is referenced by cron trigger '{trigger_name}'.",
        "data": {"environment_id": str(env_id), "trigger_name": trigger_name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None


@pytest.mark.asyncio
async def test_delete_environment_ignores_soft_deleted_trigger_reference(db_session):
    env = JoySafeterEnvironment(name=f"soft-deleted-trigger-env-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"soft-deleted-trigger-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    trigger = JoySafeterTrigger(
        name=f"deleted-env-schedule-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run later",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=False,
        next_run_at=None,
        environment_ref=env.name,
        deleted_at=utc_now(),
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()

    deleted = await delete_environment(env_id, db_session, _auth_ctx())

    assert deleted is None
    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is not None


@pytest.mark.asyncio
async def test_update_environment_config_rejects_active_task_agent_reference(db_session):
    env = JoySafeterEnvironment(name=f"update-config-env-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"update-config-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    task_id = str(task.id)

    req = UpdateEnvironmentRequest(config=EnvironmentConfig(env_vars={"NEW_ENV": "value"}))
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task_id}' via agent environment_ref. "
            "Stop or wait for the task before updating config."
        ),
        "data": {"environment_id": str(env_id), "task_id": task_id, "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert (env_row.config or {}).get("env_vars") != {"NEW_ENV": "value"}


@pytest.mark.asyncio
async def test_update_environment_name_rejects_agent_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"update-name-env-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id
    original_name = env.name

    agent = JoySafeterAgent(name=f"update-name-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_name = agent.name

    req = UpdateEnvironmentRequest(name=f"renamed-env-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_AGENT_REFERENCE",
        "message": f"Environment is referenced by agent '{agent_name}'.",
        "data": {"environment_id": str(env_id), "agent_name": agent_name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name


@pytest.mark.asyncio
async def test_update_environment_name_rejects_cron_trigger_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"update-schedule-env-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"update-schedule-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id
    original_name = env.name

    schedule = JoySafeterTrigger(
        name=f"update-env-schedule-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run later",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now(),
        environment_ref=env.name,
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(schedule)
    await db_session.commit()
    trigger_name = schedule.name

    req = UpdateEnvironmentRequest(name=f"renamed-env-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_TRIGGER_REFERENCE",
        "message": f"Environment is referenced by cron trigger '{trigger_name}'.",
        "data": {"environment_id": str(env_id), "trigger_name": trigger_name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name


@pytest.mark.asyncio
async def test_update_environment_rejects_archived_environment_with_structured_error(db_session):
    env = JoySafeterEnvironment(name=f"archived-update-env-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id
    original_name = env.name

    req = UpdateEnvironmentRequest(name=f"renamed-env-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": "Cannot update an archived environment",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name


@pytest.mark.asyncio
async def test_archive_environment_rejects_already_archived_environment_with_structured_error(db_session):
    env = JoySafeterEnvironment(name=f"already-archived-env-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": "Environment is already archived",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_environment_image_build_failure_returns_structured_error_and_rolls_back(
    db_session,
    monkeypatch,
):
    async def fail_build(env):
        raise RuntimeError("apt failed")

    monkeypatch.setattr("app.joysafeter_api.api.v1.environments._build_image_update", fail_build)

    env_name = f"build-fail-env-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(name=env_name, config=EnvironmentConfig(env_vars={"A": "B"}))
    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    detail = await handled_app_error_payload(exc_info.value, status_code=500)
    assert detail["code"] == "ENVIRONMENT_IMAGE_BUILD_FAILED"
    assert detail["message"] == "Image build failed: apt failed"
    assert detail["data"]["operation"] == "create"
    assert detail["source"] == "runtime"
    assert detail["retryable"] is True
    assert detail["user_action"] == "retry"

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.name == env_name))
    ).scalar_one()
    assert str(env_row.id) == detail["data"]["environment_id"]
    assert env_row.deleted_at is not None


@pytest.mark.asyncio
async def test_update_environment_image_build_failure_returns_structured_error_without_deleting(
    db_session,
    monkeypatch,
):
    async def fail_build(env):
        raise RuntimeError("pip failed")

    monkeypatch.setattr("app.joysafeter_api.api.v1.environments._build_image_update", fail_build)

    env = JoySafeterEnvironment(name=f"update-build-fail-env-{uuid.uuid4()}", description="", config={})
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    req = UpdateEnvironmentRequest(config=EnvironmentConfig(env_vars={"A": "B"}))
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=500) == {
        "code": "ENVIRONMENT_IMAGE_BUILD_FAILED",
        "message": "Image build failed: pip failed",
        "data": {"environment_id": str(env_id), "operation": "update"},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None
