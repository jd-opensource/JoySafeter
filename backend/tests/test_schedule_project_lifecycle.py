import json
import uuid
from datetime import timedelta

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import archive_project, restore_project
from app.joysafeter_api.api.v1.schedules import (
    create_schedule,
    enable_schedule,
    list_schedule_runs,
    trigger_schedule,
    update_schedule,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_schedule import ScheduleCreateRequest, ScheduleUpdateRequest
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
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
    def __init__(self, *, cancel_receivers: int = 1, owner: str | None = "owner-1"):
        self.cancel_receivers = cancel_receivers
        self.owner = owner
        self.published: list[tuple[str, dict]] = []
        self.acks: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        if key.startswith("joysafeter:sandbox_owner:"):
            return self.owner
        return None

    async def publish(self, channel: str, command: str) -> int:
        payload = json.loads(command)
        self.published.append((channel, payload))
        if self.cancel_receivers > 0 and payload.get("ack_key"):
            self.acks[payload["ack_key"]] = json.dumps({"command_id": payload.get("command_id"), "ok": True})
        return self.cancel_receivers

    async def blpop(self, key: str, timeout: int = 0):
        payload = self.acks.pop(key, None)
        if payload is None:
            return None
        return key, payload


class _FakeQueueRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


async def _create_project_with_agent(
    db_session,
    *,
    name: str,
    archived: bool = False,
) -> tuple[Organization, Project, JoySafeterAgent]:
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name=f"{name} Org",
        slug=f"{name.lower()}-org-{uuid.uuid4()}",
    )
    project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4()}",
        archived_at=utc_now() if archived else None,
    )
    db_session.add_all([org, project])
    await db_session.commit()
    await db_session.refresh(project)

    agent = JoySafeterAgent(
        name=f"{name.lower()}-agent-{uuid.uuid4()}",
        project_id=project.id,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return org, project, agent


async def _create_due_schedule(
    db_session,
    *,
    project: Project,
    agent: JoySafeterAgent,
    name: str,
) -> JoySafeterSchedule:
    schedule = JoySafeterSchedule(
        name=f"{name}-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt="run scheduled project audit",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now() - timedelta(minutes=10),
        project_id=project.id,
        user_id="schedule-owner",
        org_id=project.org_id,
        concurrency_policy="allow",
    )
    db_session.add(schedule)
    await db_session.commit()
    await db_session.refresh(schedule)
    return schedule


async def _create_environment(db_session, *, project: Project, archived: bool = False) -> JoySafeterEnvironment:
    env = JoySafeterEnvironment(
        name=f"schedule-env-{uuid.uuid4()}",
        description="",
        project_id=project.id,
        archived_at=utc_now() if archived else None,
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest.mark.asyncio
async def test_scheduler_claim_skips_archived_project_schedules_without_disabling_user_intent(db_session):
    _, active_project, active_agent = await _create_project_with_agent(db_session, name="Active")
    _, archived_project, archived_agent = await _create_project_with_agent(
        db_session,
        name="Archived",
        archived=True,
    )
    active_schedule = await _create_due_schedule(
        db_session,
        project=active_project,
        agent=active_agent,
        name="active",
    )
    archived_schedule = await _create_due_schedule(
        db_session,
        project=archived_project,
        agent=archived_agent,
        name="archived",
    )
    active_schedule_id = active_schedule.id
    archived_schedule_id = archived_schedule.id

    claimed = await JoySafeterScheduleService(db_session).claim_due_schedules(
        worker_id="worker-1",
        limit=10,
        lock_grace_sec=120,
    )

    assert [schedule.id for schedule in claimed] == [active_schedule_id]

    db_session.expire_all()
    archived_row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == archived_schedule_id))
    ).scalar_one()
    assert archived_row.enabled is True
    assert archived_row.next_run_at is not None
    assert archived_row.locked_by is None
    assert archived_row.locked_at is None


@pytest.mark.asyncio
async def test_scheduler_claim_preserves_global_schedule_support(db_session):
    agent = JoySafeterAgent(name=f"global-schedule-agent-{uuid.uuid4()}", project_id=None)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    schedule = JoySafeterSchedule(
        name=f"global-schedule-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt="run global scheduled task",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now() - timedelta(minutes=5),
        project_id=None,
        user_id=None,
        org_id=None,
        concurrency_policy="allow",
    )
    db_session.add(schedule)
    await db_session.commit()
    await db_session.refresh(schedule)
    schedule_id = schedule.id

    claimed = await JoySafeterScheduleService(db_session).claim_due_schedules(
        worker_id="global-worker",
        limit=10,
        lock_grace_sec=120,
    )

    assert [row.id for row in claimed] == [schedule_id]


@pytest.mark.asyncio
async def test_project_archive_pauses_schedules_and_restore_resumes_from_future_slot(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="Lifecycle")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="lifecycle")
    org_id = org.id
    project_id = project.id
    schedule_id = schedule.id
    schedule.locked_by = "stale-worker"
    schedule.locked_at = utc_now() - timedelta(minutes=20)
    await db_session.commit()

    response = await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert response == {"status": "archived"}
    db_session.expire_all()
    archived_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert archived_schedule.enabled is True
    assert archived_schedule.next_run_at is None
    assert archived_schedule.locked_by is None
    assert archived_schedule.locked_at is None

    before_restore = utc_now()
    restored = await restore_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert restored.archived_at is None
    db_session.expire_all()
    restored_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert restored_schedule.enabled is True
    assert restored_schedule.next_run_at is not None
    assert restored_schedule.next_run_at > before_restore
    assert restored_schedule.locked_by is None
    assert restored_schedule.locked_at is None


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_schedule_after_project_archived_race(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="AdvanceRace")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="advance-race")
    org_id = org.id
    project_id = project.id
    schedule_id = schedule.id

    claimed = await JoySafeterScheduleService(db_session).claim_due_schedules(
        worker_id="worker-before-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [schedule_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))
    await JoySafeterScheduleService(db_session).advance_after_fire(schedule_id, fired_slot)

    db_session.expire_all()
    archived_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert archived_schedule.enabled is True
    assert archived_schedule.next_run_at is None
    assert archived_schedule.locked_by is None
    assert archived_schedule.locked_at is None
    assert archived_schedule.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_agent_archive_pauses_target_schedules_without_disabling_user_intent(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentArchive")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="agent-archive")
    schedule_id = schedule.id
    agent_id = agent.id
    schedule.locked_by = "stale-agent-worker"
    schedule.locked_at = utc_now() - timedelta(minutes=20)
    await db_session.commit()

    archived, archived_session_ids = await JoySafeterAgentService(db_session).archive_agent_with_sessions(
        agent_id,
        project_id=project.id,
    )

    assert archived is True
    assert archived_session_ids == []
    db_session.expire_all()
    archived_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert archived_schedule.enabled is True
    assert archived_schedule.next_run_at is None
    assert archived_schedule.locked_by is None
    assert archived_schedule.locked_at is None


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_schedule_after_agent_archived_race(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentAdvanceRace")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="agent-advance-race")
    schedule_id = schedule.id
    agent_id = agent.id

    claimed = await JoySafeterScheduleService(db_session).claim_due_schedules(
        worker_id="worker-before-agent-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [schedule_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    agent.archived_at = utc_now()
    await db_session.commit()
    await JoySafeterScheduleService(db_session).advance_after_fire(schedule_id, fired_slot)

    db_session.expire_all()
    archived_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert archived_schedule.agent_id == agent_id
    assert archived_schedule.enabled is True
    assert archived_schedule.next_run_at is None
    assert archived_schedule.locked_by is None
    assert archived_schedule.locked_at is None
    assert archived_schedule.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_task_submission_admission_rejects_archived_project_after_scheduler_claim_race(db_session):
    _, project, _ = await _create_project_with_agent(db_session, name="Race", archived=True)

    with pytest.raises(AppError) as exc_info:
        await TaskSubmissionService(db_session).enforce_admission(
            project_id=project.id,
            user_id="schedule-owner",
            enforce_user_quota=False,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "Project is archived and cannot create new tasks.",
        "data": {"project_id": project.id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_schedule_rejects_archived_agent_without_creating_schedule(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedAgentCreate")
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_schedule(
            ScheduleCreateRequest(
                name=f"blocked-{uuid.uuid4()}",
                agent_id=agent.id,
                prompt="should not schedule archived agent",
                cron_expr="*/5 * * * *",
                timezone="UTC",
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new scheduled runs.",
        "data": {"agent_id": str(agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    count = (
        (await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert count == []


@pytest.mark.asyncio
async def test_manual_schedule_trigger_rejects_archived_agent_without_creating_task(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedAgentTrigger")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="archived-agent-trigger")
    schedule_id = schedule.id
    agent_id = agent.id
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await trigger_schedule(schedule_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new scheduled runs.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.schedule_id == schedule_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_manual_schedule_trigger_stores_full_execution_snapshot(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    org, project, agent = await _create_project_with_agent(db_session, name="ManualTriggerSnapshot")
    env = await _create_environment(db_session, project=project)
    environment_ref = f"env_{env.id}"
    env.config = {"setup_commands": ["echo before"], "network": {"mode": "egress"}}
    env.image_tag = "joysafeter/runtime:before"
    env.image_version = 7
    agent.model = {"provider": "openai", "model": "snapshot-model"}
    agent.system_prompt = "snapshot system"
    agent.env = {"SNAPSHOT_ENV": "before"}
    agent.mcp_configs = [{"name": "snapshot-mcp", "url": "https://mcp.before.test"}]
    agent.tools = [{"name": "snapshot-tool"}]
    agent.permission_mode = "bypassPermissions"
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="manual-snapshot")
    schedule.environment_ref = environment_ref
    await db_session.commit()

    response = await trigger_schedule(schedule.id, db_session, _admin_ctx(project.id, org.id))

    assert redis.rpushed == [("joysafeter:global_queue", str(response.task_id))]
    db_session.expire_all()
    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == response.session_id))
    ).scalar_one()
    snapshot = session.agent_snapshot
    assert snapshot["schema"] == "joysafeter.agent_execution_snapshot.v1"
    assert snapshot["model"] == {"provider": "openai", "model": "snapshot-model"}
    assert snapshot["system_prompt"] == "snapshot system"
    assert snapshot["env"] == {"SNAPSHOT_ENV": "before"}
    assert snapshot["mcp_configs"] == [{"name": "snapshot-mcp", "url": "https://mcp.before.test"}]
    assert snapshot["tools"] == [{"name": "snapshot-tool"}]
    assert snapshot["environment_ref"] == environment_ref
    assert snapshot["environment"]["config"] == {"setup_commands": ["echo before"], "network": {"mode": "egress"}}
    assert snapshot["environment"]["image_tag"] == "joysafeter/runtime:before"
    assert snapshot["environment"]["image_version"] == 7

    agent.model = {"provider": "openai", "model": "mutated-model"}
    agent.system_prompt = "mutated system"
    agent.env = {"SNAPSHOT_ENV": "after"}
    env.config = {"setup_commands": ["echo after"], "network": {"mode": "blocked"}}
    env.image_tag = "joysafeter/runtime:after"
    env.image_version = 8
    await db_session.commit()

    db_session.expire_all()
    unchanged = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == response.session_id))
    ).scalar_one()
    assert unchanged.agent_snapshot == snapshot


@pytest.mark.asyncio
async def test_schedule_run_children_reject_cross_project_parent_at_service_boundary(db_session):
    org_a, project_a, _agent_a = await _create_project_with_agent(db_session, name="ScheduleRunsA")
    _org_b, project_b, agent_b = await _create_project_with_agent(db_session, name="ScheduleRunsB")
    schedule_b = await _create_due_schedule(db_session, project=project_b, agent=agent_b, name="run-history")
    task_b = JoySafeterTask(
        agent_id=agent_b.id,
        schedule_id=schedule_b.id,
        project_id=project_b.id,
        prompt="scheduled run",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task_b)
    await db_session.commit()
    schedule_b_id = schedule_b.id
    task_b_id = task_b.id

    svc = JoySafeterScheduleService(db_session)
    cross_runs = await svc.list_runs(schedule_b_id, project_id=project_a.id)
    cross_active = await svc.get_active_tasks(schedule_b_id, project_id=project_a.id)

    assert cross_runs is None
    assert list(cross_active) == []

    project_b_runs = await svc.list_runs(schedule_b_id, project_id=project_b.id)
    project_b_active = await svc.get_active_tasks(schedule_b_id, project_id=project_b.id)
    assert project_b_runs is not None
    assert [str(run.id) for run in project_b_runs] == [str(task_b_id)]
    assert [str(task.id) for task in project_b_active] == [str(task_b_id)]

    with pytest.raises(AppError) as exc_info:
        await list_schedule_runs(schedule_b_id, 50, 0, db_session, _admin_ctx(project_a.id, org_a.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SCHEDULE_NOT_FOUND",
        "message": "Schedule not found",
        "data": {"schedule_id": str(schedule_b_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_schedule_rejects_missing_environment_without_creating_schedule(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="MissingScheduleEnv")
    missing_ref = f"env_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await create_schedule(
            ScheduleCreateRequest(
                name=f"missing-env-{uuid.uuid4()}",
                agent_id=agent.id,
                prompt="should not schedule missing env",
                cron_expr="*/5 * * * *",
                timezone="UTC",
                environment_ref=missing_ref,
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SCHEDULE_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    schedules = (
        (await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert schedules == []


@pytest.mark.asyncio
async def test_schedule_service_rejects_cross_project_agent_without_creating_schedule(db_session):
    _, project, _ = await _create_project_with_agent(db_session, name="ScheduleSvcProjectA")
    _, other_project, other_agent = await _create_project_with_agent(db_session, name="ScheduleSvcProjectB")

    with pytest.raises(AppError) as exc_info:
        await JoySafeterScheduleService(db_session).create(
            name=f"cross-agent-{uuid.uuid4()}",
            agent_id=other_agent.id,
            prompt="must not bind to another project's agent",
            cron_expr="*/5 * * * *",
            timezone="UTC",
            project_id=project.id,
            org_id=project.org_id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SCHEDULE_AGENT_NOT_FOUND",
        "message": "Agent not found",
        "data": {"agent_id": str(other_agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    schedules = (
        (
            await db_session.execute(
                select(JoySafeterSchedule).where(JoySafeterSchedule.project_id.in_([project.id, other_project.id]))
            )
        )
        .scalars()
        .all()
    )
    assert schedules == []


@pytest.mark.asyncio
async def test_schedule_service_rejects_cross_project_environment_without_creating_schedule(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="ScheduleSvcEnvProjectA")
    _, other_project, _ = await _create_project_with_agent(db_session, name="ScheduleSvcEnvProjectB")
    other_env = await _create_environment(db_session, project=other_project)
    other_env_ref = f"env_{other_env.id}"

    with pytest.raises(AppError) as exc_info:
        await JoySafeterScheduleService(db_session).create(
            name=f"cross-env-{uuid.uuid4()}",
            agent_id=agent.id,
            prompt="must not bind to another project's environment",
            cron_expr="*/5 * * * *",
            timezone="UTC",
            environment_ref=other_env_ref,
            project_id=project.id,
            org_id=project.org_id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SCHEDULE_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {other_env_ref}",
        "data": {"environment_ref": other_env_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    schedules = (
        (await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert schedules == []


@pytest.mark.asyncio
async def test_create_schedule_rejects_archived_effective_environment_without_creating_schedule(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedScheduleEnv")
    env = await _create_environment(db_session, project=project, archived=True)
    env_ref = f"env_{env.id}"

    with pytest.raises(AppError) as exc_info:
        await create_schedule(
            ScheduleCreateRequest(
                name=f"archived-env-{uuid.uuid4()}",
                agent_id=agent.id,
                prompt="should not schedule archived env",
                cron_expr="*/5 * * * *",
                timezone="UTC",
                environment_ref=env_ref,
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {env_ref}",
        "data": {"environment_ref": env_ref, "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    schedules = (
        (await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert schedules == []


@pytest.mark.asyncio
async def test_manual_schedule_trigger_rejects_archived_environment_without_creating_task(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="TriggerArchivedEnv")
    env = await _create_environment(db_session, project=project)
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="trigger-archived-env")
    schedule.environment_ref = f"env_{env.id}"
    schedule_id = schedule.id
    env.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await trigger_schedule(schedule_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: env_{env.id}",
        "data": {"environment_ref": f"env_{env.id}", "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.schedule_id == schedule_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_update_schedule_rejects_missing_environment_without_persisting_ref(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="UpdateMissingEnv")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="update-missing-env")
    schedule_id = schedule.id
    missing_ref = f"env_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await update_schedule(
            schedule_id,
            ScheduleUpdateRequest(environment_ref=missing_ref),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SCHEDULE_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert row.environment_ref is None


@pytest.mark.asyncio
async def test_schedule_service_update_rejects_cross_project_environment_without_persisting_ref(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="ScheduleSvcUpdateProjectA")
    _, other_project, _ = await _create_project_with_agent(db_session, name="ScheduleSvcUpdateProjectB")
    other_env = await _create_environment(db_session, project=other_project)
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="svc-update-cross-env")
    schedule_id = schedule.id
    other_env_ref = f"env_{other_env.id}"

    with pytest.raises(AppError) as exc_info:
        await JoySafeterScheduleService(db_session).update(
            schedule_id,
            project.id,
            environment_ref=other_env_ref,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SCHEDULE_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {other_env_ref}",
        "data": {"environment_ref": other_env_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert row.environment_ref is None


@pytest.mark.asyncio
async def test_update_schedule_rejects_duplicate_name_without_persisting_change(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="UpdateDuplicateName")
    existing = await _create_due_schedule(db_session, project=project, agent=agent, name="existing-name")
    target = await _create_due_schedule(db_session, project=project, agent=agent, name="target-name")
    target_id = target.id
    original_name = target.name

    with pytest.raises(AppError) as exc_info:
        await update_schedule(
            target_id,
            ScheduleUpdateRequest(name=existing.name),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SCHEDULE_NAME_EXISTS",
        "message": f"A schedule named '{existing.name}' already exists in this project",
        "data": {"name": existing.name},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == target_id))).scalar_one()
    assert row.name == original_name


@pytest.mark.asyncio
async def test_enable_schedule_rejects_archived_agent_without_rearming_schedule(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="EnableArchivedAgent")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="enable-archived-agent")
    schedule_id = schedule.id
    agent_id = agent.id
    schedule.enabled = False
    schedule.next_run_at = None
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await enable_schedule(schedule_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new scheduled runs.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert row.enabled is False
    assert row.next_run_at is None


@pytest.mark.asyncio
async def test_schedule_service_enable_rejects_archived_agent_without_rearming_schedule(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="ScheduleSvcEnableArchivedAgent")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="svc-enable-archived")
    schedule_id = schedule.id
    agent_id = agent.id
    schedule.enabled = False
    schedule.next_run_at = None
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await JoySafeterScheduleService(db_session).update(schedule_id, project.id, enabled=True)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new scheduled runs.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert row.enabled is False
    assert row.next_run_at is None


@pytest.mark.asyncio
async def test_enable_schedule_rejects_archived_environment_without_rearming_schedule(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="EnableArchivedEnv")
    env = await _create_environment(db_session, project=project)
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="enable-archived-env")
    schedule_id = schedule.id
    schedule.environment_ref = f"env_{env.id}"
    schedule.enabled = False
    schedule.next_run_at = None
    env.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await enable_schedule(schedule_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: env_{env.id}",
        "data": {"environment_ref": f"env_{env.id}", "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert row.enabled is False
    assert row.next_run_at is None


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_schedule_after_environment_archived_race(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="EnvAdvanceRace")
    env = await _create_environment(db_session, project=project)
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="env-advance-race")
    schedule.environment_ref = f"env_{env.id}"
    await db_session.commit()
    schedule_id = schedule.id

    claimed = await JoySafeterScheduleService(db_session).claim_due_schedules(
        worker_id="worker-before-env-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [schedule_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    env.archived_at = utc_now()
    await db_session.commit()
    await JoySafeterScheduleService(db_session).advance_after_fire(schedule_id, fired_slot)

    db_session.expire_all()
    paused_schedule = (
        await db_session.execute(select(JoySafeterSchedule).where(JoySafeterSchedule.id == schedule_id))
    ).scalar_one()
    assert paused_schedule.enabled is True
    assert paused_schedule.next_run_at is None
    assert paused_schedule.locked_by is None
    assert paused_schedule.locked_at is None
    assert paused_schedule.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_scheduled_task_cancel_does_not_mark_cancelled_when_runtime_relay_fails(db_session, monkeypatch):
    redis = _FakeCommandRedis(cancel_receivers=0)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    _, project, agent = await _create_project_with_agent(db_session, name="ReplaceRelayFail")
    schedule = await _create_due_schedule(db_session, project=project, agent=agent, name="replace-relay-fail")
    schedule.concurrency_policy = "replace"
    session = JoySafeterSession(agent_id=agent.id, project_id=project.id, status="running")
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
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        sandbox_id=sandbox.id,
        schedule_id=schedule.id,
        project_id=project.id,
        prompt="still running scheduled slot",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    schedule_id = schedule.id
    task_id = task.id
    session_id = session.id
    sandbox_id = sandbox.id

    with pytest.raises(AppError) as exc_info:
        await TaskCancellationService(db_session).cancel(
            task,
            reason=f"Replaced by schedule {schedule.id} slot {utc_now().isoformat()}",
        )

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
    assert [(channel, payload["type"]) for channel, payload in redis.published] == [
        ("joysafeter:cmd:owner-1", "cancel")
    ]

    db_session.expire_all()
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.schedule_id == schedule_id)))
        .scalars()
        .all()
    )
    assert [str(row.id) for row in tasks] == [str(task_id)]
    assert tasks[0].status == JoySafeterTaskStatus.RUNNING.value
