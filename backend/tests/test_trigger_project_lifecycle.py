import json
import uuid
from datetime import timedelta

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select
from starlette.requests import Request

from app.joysafeter_api.api.v1.auth import archive_project, restore_project
from app.joysafeter_api.api.v1.triggers import (
    create_trigger,
    list_trigger_runs,
    run_trigger_now,
    update_trigger,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.schemas.joysafeter_trigger import TriggerCreateRequest, TriggerUpdateRequest
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
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


def _fake_request() -> Request:
    """Minimal ASGI request so route handlers that build webhook URLs work."""
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
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


async def _create_due_trigger(
    db_session,
    *,
    project: Project,
    agent: JoySafeterAgent,
    name: str,
) -> JoySafeterTrigger:
    trigger = JoySafeterTrigger(
        name=f"{name}-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run scheduled project audit",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now() - timedelta(minutes=10),
        project_id=project.id,
        user_id="trigger-owner",
        org_id=project.org_id,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


async def _create_environment(db_session, *, project: Project, archived: bool = False) -> JoySafeterEnvironment:
    env = JoySafeterEnvironment(
        name=f"trigger-env-{uuid.uuid4()}",
        description="",
        project_id=project.id,
        archived_at=utc_now() if archived else None,
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest.mark.asyncio
async def test_scheduler_claim_skips_archived_project_triggers_without_disabling_user_intent(db_session):
    _, active_project, active_agent = await _create_project_with_agent(db_session, name="Active")
    _, archived_project, archived_agent = await _create_project_with_agent(
        db_session,
        name="Archived",
        archived=True,
    )
    active_trigger = await _create_due_trigger(db_session, project=active_project, agent=active_agent, name="active")
    archived_trigger = await _create_due_trigger(db_session, project=archived_project, agent=archived_agent, name="archived")
    active_trigger_id = active_trigger.id
    archived_trigger_id = archived_trigger.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-1",
        limit=10,
        lock_grace_sec=120,
    )

    assert [trigger.id for trigger in claimed] == [active_trigger_id]

    db_session.expire_all()
    archived_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == archived_trigger_id))
    ).scalar_one()
    assert archived_row.enabled is True
    assert archived_row.next_run_at is not None
    assert archived_row.locked_by is None
    assert archived_row.locked_at is None


@pytest.mark.asyncio
async def test_scheduler_claim_preserves_global_trigger_support(db_session):
    agent = JoySafeterAgent(name=f"global-trigger-agent-{uuid.uuid4()}", project_id=None)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    trigger = JoySafeterTrigger(
        name=f"global-trigger-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run global scheduled task",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now() - timedelta(minutes=5),
        project_id=None,
        user_id=None,
        org_id=None,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    trigger_id = trigger.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="global-worker",
        limit=10,
        lock_grace_sec=120,
    )

    assert [row.id for row in claimed] == [trigger_id]


@pytest.mark.asyncio
async def test_scheduler_claim_skips_deleted_or_archived_agent_triggers_without_mutating_rows(db_session):
    _, active_project, active_agent = await _create_project_with_agent(db_session, name="ActiveAgentClaim")
    _, deleted_project, deleted_agent = await _create_project_with_agent(db_session, name="DeletedAgentClaim")
    _, archived_project, archived_agent = await _create_project_with_agent(db_session, name="ArchivedAgentClaim")
    active_trigger = await _create_due_trigger(db_session, project=active_project, agent=active_agent, name="active-agent")
    deleted_trigger = await _create_due_trigger(db_session, project=deleted_project, agent=deleted_agent, name="deleted-agent")
    archived_trigger = await _create_due_trigger(
        db_session,
        project=archived_project,
        agent=archived_agent,
        name="archived-agent",
    )
    active_trigger_id = active_trigger.id
    deleted_trigger_id = deleted_trigger.id
    archived_trigger_id = archived_trigger.id
    deleted_agent.deleted_at = utc_now()
    archived_agent.archived_at = utc_now()
    await db_session.commit()

    assert await JoySafeterTriggerService(db_session).earliest_next_run() == active_trigger.next_run_at

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-agent-gate",
        limit=10,
        lock_grace_sec=120,
    )

    assert [trigger.id for trigger in claimed] == [active_trigger_id]
    assert await JoySafeterTriggerService(db_session).earliest_next_run() is None

    db_session.expire_all()
    deleted_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == deleted_trigger_id))
    ).scalar_one()
    archived_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == archived_trigger_id))
    ).scalar_one()
    assert deleted_row.next_run_at is not None
    assert deleted_row.locked_by is None
    assert deleted_row.locked_at is None
    assert archived_row.next_run_at is not None
    assert archived_row.locked_by is None
    assert archived_row.locked_at is None


@pytest.mark.asyncio
async def test_earliest_next_run_ignores_fresh_claim_locks(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="EarliestLock")
    locked_trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="locked-earliest")
    future_trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="future-earliest")
    future_run_at = utc_now() + timedelta(hours=1)
    locked_trigger.locked_by = "worker-already-processing"
    locked_trigger.locked_at = utc_now()
    future_trigger.next_run_at = future_run_at
    await db_session.commit()

    earliest = await JoySafeterTriggerService(db_session).earliest_next_run(lock_grace_sec=120)

    assert earliest == future_run_at


@pytest.mark.asyncio
async def test_scheduler_claim_skips_trigger_environment_refs_that_are_not_live(db_session):
    _, active_project, active_agent = await _create_project_with_agent(db_session, name="ActiveTriggerEnvClaim")
    _, archived_project, archived_agent = await _create_project_with_agent(db_session, name="ArchivedTriggerEnvClaim")
    _, deleted_project, deleted_agent = await _create_project_with_agent(db_session, name="DeletedTriggerEnvClaim")
    live_env = await _create_environment(db_session, project=active_project)
    archived_env = await _create_environment(db_session, project=archived_project)
    deleted_env = await _create_environment(db_session, project=deleted_project)
    active_trigger = await _create_due_trigger(db_session, project=active_project, agent=active_agent, name="active-env")
    archived_trigger = await _create_due_trigger(
        db_session,
        project=archived_project,
        agent=archived_agent,
        name="archived-env",
    )
    deleted_trigger = await _create_due_trigger(
        db_session,
        project=deleted_project,
        agent=deleted_agent,
        name="deleted-env",
    )
    active_trigger_id = active_trigger.id
    archived_trigger_id = archived_trigger.id
    deleted_trigger_id = deleted_trigger.id
    active_trigger.environment_ref = live_env.name
    archived_trigger.environment_ref = archived_env.name
    deleted_trigger.environment_ref = f"env_{deleted_env.id}"
    archived_env.archived_at = utc_now()
    deleted_env.deleted_at = utc_now()
    await db_session.commit()

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-trigger-env-gate",
        limit=10,
        lock_grace_sec=120,
    )

    assert [trigger.id for trigger in claimed] == [active_trigger_id]
    assert await JoySafeterTriggerService(db_session).earliest_next_run() is None

    db_session.expire_all()
    archived_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == archived_trigger_id))
    ).scalar_one()
    deleted_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == deleted_trigger_id))
    ).scalar_one()
    assert archived_row.locked_by is None
    assert archived_row.locked_at is None
    assert archived_row.next_run_at is not None
    assert deleted_row.locked_by is None
    assert deleted_row.locked_at is None
    assert deleted_row.next_run_at is not None


@pytest.mark.asyncio
async def test_scheduler_claim_skips_agent_environment_refs_that_are_not_live(db_session):
    _, active_project, active_agent = await _create_project_with_agent(db_session, name="ActiveAgentEnvClaim")
    _, archived_project, archived_agent = await _create_project_with_agent(db_session, name="ArchivedAgentEnvClaim")
    _, deleted_project, deleted_agent = await _create_project_with_agent(db_session, name="DeletedAgentEnvClaim")
    live_env = await _create_environment(db_session, project=active_project)
    archived_env = await _create_environment(db_session, project=archived_project)
    deleted_env = await _create_environment(db_session, project=deleted_project)
    active_agent.environment_ref = live_env.name
    archived_agent.environment_ref = f"env_{archived_env.id}"
    deleted_agent.environment_ref = str(deleted_env.id)
    archived_env.archived_at = utc_now()
    deleted_env.deleted_at = utc_now()
    active_trigger = await _create_due_trigger(db_session, project=active_project, agent=active_agent, name="active-agent-env")
    archived_trigger = await _create_due_trigger(
        db_session,
        project=archived_project,
        agent=archived_agent,
        name="archived-agent-env",
    )
    deleted_trigger = await _create_due_trigger(
        db_session,
        project=deleted_project,
        agent=deleted_agent,
        name="deleted-agent-env",
    )
    active_trigger_id = active_trigger.id
    archived_trigger_id = archived_trigger.id
    deleted_trigger_id = deleted_trigger.id
    await db_session.commit()

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-agent-env-gate",
        limit=10,
        lock_grace_sec=120,
    )

    assert [trigger.id for trigger in claimed] == [active_trigger_id]
    assert await JoySafeterTriggerService(db_session).earliest_next_run() is None

    db_session.expire_all()
    archived_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == archived_trigger_id))
    ).scalar_one()
    deleted_row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == deleted_trigger_id))
    ).scalar_one()
    assert archived_row.locked_by is None
    assert archived_row.locked_at is None
    assert archived_row.next_run_at is not None
    assert deleted_row.locked_by is None
    assert deleted_row.locked_at is None
    assert deleted_row.next_run_at is not None


@pytest.mark.asyncio
async def test_project_archive_pauses_triggers_and_restore_resumes_from_future_slot(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="Lifecycle")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="lifecycle")
    org_id = org.id
    project_id = project.id
    trigger_id = trigger.id
    trigger.locked_by = "stale-worker"
    trigger.locked_at = utc_now() - timedelta(minutes=20)
    await db_session.commit()

    response = await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert response == {"status": "archived"}
    db_session.expire_all()
    archived_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert archived_trigger.enabled is True
    assert archived_trigger.next_run_at is None
    assert archived_trigger.locked_by is None
    assert archived_trigger.locked_at is None

    before_restore = utc_now()
    restored = await restore_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert restored.archived_at is None
    db_session.expire_all()
    restored_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert restored_trigger.enabled is True
    assert restored_trigger.next_run_at is not None
    assert restored_trigger.next_run_at > before_restore
    assert restored_trigger.locked_by is None
    assert restored_trigger.locked_at is None


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_trigger_after_project_archived_race(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="AdvanceRace")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="advance-race")
    org_id = org.id
    project_id = project.id
    trigger_id = trigger.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-before-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [trigger_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))
    await JoySafeterTriggerService(db_session).advance_after_fire(trigger_id, fired_slot)

    db_session.expire_all()
    archived_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert archived_trigger.enabled is True
    assert archived_trigger.next_run_at is None
    assert archived_trigger.locked_by is None
    assert archived_trigger.locked_at is None
    assert archived_trigger.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_agent_archive_pauses_target_triggers_without_disabling_user_intent(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentArchive")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="agent-archive")
    trigger_id = trigger.id
    agent_id = agent.id
    trigger.locked_by = "stale-agent-worker"
    trigger.locked_at = utc_now() - timedelta(minutes=20)
    await db_session.commit()

    archived, archived_session_ids = await JoySafeterAgentService(db_session).archive_agent_with_sessions(
        agent_id,
        project_id=project.id,
    )

    assert archived is True
    assert archived_session_ids == []
    db_session.expire_all()
    archived_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert archived_trigger.enabled is True
    assert archived_trigger.next_run_at is None
    assert archived_trigger.locked_by is None
    assert archived_trigger.locked_at is None


@pytest.mark.asyncio
async def test_agent_soft_delete_pauses_target_triggers_without_disabling_user_intent(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentSoftDelete")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="agent-soft-delete")
    trigger_id = trigger.id
    trigger.locked_by = "stale-delete-worker"
    trigger.locked_at = utc_now() - timedelta(minutes=20)
    trigger.pending_slot_at = utc_now() - timedelta(minutes=5)
    trigger.slot_attempts = 1
    await db_session.commit()

    deleted = await JoySafeterAgentService(db_session).delete_agent(
        agent.id,
        project_id=project.id,
    )

    assert deleted is True
    db_session.expire_all()
    deleted_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert deleted_trigger.enabled is True
    assert deleted_trigger.next_run_at is None
    assert deleted_trigger.locked_by is None
    assert deleted_trigger.locked_at is None
    assert deleted_trigger.pending_slot_at is None
    assert deleted_trigger.slot_attempts == 0


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_trigger_after_agent_archived_race(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentAdvanceRace")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="agent-advance-race")
    trigger_id = trigger.id
    agent_id = agent.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-before-agent-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [trigger_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    agent.archived_at = utc_now()
    await db_session.commit()
    await JoySafeterTriggerService(db_session).advance_after_fire(trigger_id, fired_slot)

    db_session.expire_all()
    archived_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert archived_trigger.agent_id == agent_id
    assert archived_trigger.enabled is True
    assert archived_trigger.next_run_at is None
    assert archived_trigger.locked_by is None
    assert archived_trigger.locked_at is None
    assert archived_trigger.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_trigger_after_agent_soft_deleted_race(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="AgentDeleteAdvanceRace")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="agent-delete-advance-race")
    trigger_id = trigger.id
    agent_id = agent.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-before-agent-delete",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [trigger_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    agent.deleted_at = utc_now()
    await db_session.commit()
    await JoySafeterTriggerService(db_session).advance_after_fire(trigger_id, fired_slot, record_attempt=False)

    db_session.expire_all()
    deleted_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert deleted_trigger.agent_id == agent_id
    assert deleted_trigger.enabled is True
    assert deleted_trigger.next_run_at is None
    assert deleted_trigger.locked_by is None
    assert deleted_trigger.locked_at is None
    assert deleted_trigger.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_task_submission_admission_rejects_archived_project_after_scheduler_claim_race(db_session):
    _, project, _ = await _create_project_with_agent(db_session, name="Race", archived=True)

    with pytest.raises(AppError) as exc_info:
        await TaskSubmissionService(db_session).enforce_admission(
            project_id=project.id,
            user_id="trigger-owner",
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
async def test_create_trigger_rejects_archived_agent_without_creating_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedAgentCreate")
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_trigger(
            _fake_request(),
            TriggerCreateRequest(
                name=f"blocked-{uuid.uuid4()}",
                type="cron",
                agent_id=agent.id,
                prompt_template="should not schedule archived agent",
                cron_expr="*/5 * * * *",
                timezone="UTC",
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new triggered runs.",
        "data": {"agent_id": str(agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    count = (
        (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert count == []


@pytest.mark.asyncio
async def test_create_cron_trigger_in_paused_project_does_not_arm_next_run(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="PausedProjectCreate")
    project.triggers_paused = True
    await db_session.commit()

    response = await create_trigger(
        _fake_request(),
        TriggerCreateRequest(
            name=f"paused-create-{uuid.uuid4()}",
            type="cron",
            agent_id=agent.id,
            prompt_template="should stay parked while project is paused",
            cron_expr="*/5 * * * *",
            timezone="UTC",
        ),
        db_session,
        _admin_ctx(project.id, org.id),
    )

    assert response.next_run_at is None
    created_id = uuid.UUID(str(response.id).removeprefix("trig_"))
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == created_id))).scalar_one()
    assert row.next_run_at is None
    assert row.config["next_run_at"] is None


@pytest.mark.asyncio
async def test_create_trigger_rejects_archived_project_without_creating_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedProjectCreate")
    project.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_trigger(
            _fake_request(),
            TriggerCreateRequest(
                name=f"archived-project-create-{uuid.uuid4()}",
                type="cron",
                agent_id=agent.id,
                prompt_template="should not create in archived project",
                cron_expr="*/5 * * * *",
                timezone="UTC",
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "Project is archived and cannot create new triggered runs.",
        "data": {"project_id": project.id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    count = (
        (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert count == []


@pytest.mark.asyncio
async def test_manual_trigger_run_rejects_archived_agent_without_creating_task(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedAgentTrigger")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="archived-agent-trigger")
    trigger_id = trigger.id
    agent_id = agent.id
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await run_trigger_now(trigger_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new triggered runs.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_manual_trigger_run_skips_when_project_archived(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedManualTrigger")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="archived-manual")
    trigger_id = trigger.id
    project.archived_at = utc_now()
    await db_session.commit()

    response = await run_trigger_now(trigger_id, db_session, _admin_ctx(project.id, org.id))

    assert response.status == "skipped"
    assert response.task_id is None
    assert response.session_id is None
    assert response.deduped is False
    assert response.reason == "project is archived"
    assert redis.rpushed == []
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_manual_trigger_run_skips_when_project_triggers_paused(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    org, project, agent = await _create_project_with_agent(db_session, name="PausedManualTrigger")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="paused-manual")
    trigger_id = trigger.id
    project.triggers_paused = True
    await db_session.commit()

    response = await run_trigger_now(trigger_id, db_session, _admin_ctx(project.id, org.id))

    assert response.status == "skipped"
    assert response.task_id is None
    assert response.session_id is None
    assert response.deduped is False
    assert response.reason == "triggers are paused for this project"
    assert redis.rpushed == []
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_manual_trigger_run_stores_full_execution_snapshot(db_session, monkeypatch):
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
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="manual-snapshot")
    trigger.environment_ref = environment_ref
    await db_session.commit()

    response = await run_trigger_now(trigger.id, db_session, _admin_ctx(project.id, org.id))

    task_uuid = uuid.UUID(response.task_id.removeprefix("task_"))
    session_uuid = uuid.UUID(response.session_id.removeprefix("sess_"))
    assert redis.rpushed == [("joysafeter:global_queue", str(task_uuid))]
    db_session.expire_all()
    session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_uuid))
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
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_uuid))
    ).scalar_one()
    assert unchanged.agent_snapshot == snapshot


@pytest.mark.asyncio
async def test_trigger_run_children_reject_cross_project_parent_at_service_boundary(db_session):
    org_a, project_a, _agent_a = await _create_project_with_agent(db_session, name="TriggerRunsA")
    _org_b, project_b, agent_b = await _create_project_with_agent(db_session, name="TriggerRunsB")
    trigger_b = await _create_due_trigger(db_session, project=project_b, agent=agent_b, name="run-history")
    task_b = JoySafeterTask(
        agent_id=agent_b.id,
        trigger_id=trigger_b.id,
        project_id=project_b.id,
        prompt="scheduled run",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task_b)
    await db_session.commit()
    trigger_b_id = trigger_b.id
    task_b_id = task_b.id

    svc = JoySafeterTriggerService(db_session)
    cross_runs = await svc.list_runs(trigger_b_id, project_id=project_a.id)
    assert cross_runs is None

    project_b_runs = await svc.list_runs(trigger_b_id, project_id=project_b.id)
    assert project_b_runs is not None
    assert [str(run.id) for run in project_b_runs] == [str(task_b_id)]

    with pytest.raises(AppError) as exc_info:
        await list_trigger_runs(trigger_b_id, 50, 0, db_session, _admin_ctx(project_a.id, org_a.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "TRIGGER_NOT_FOUND",
        "message": "Trigger not found",
        "data": {"trigger_id": str(trigger_b_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_trigger_rejects_missing_environment_without_creating_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="MissingTriggerEnv")
    missing_ref = f"env_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await create_trigger(
            _fake_request(),
            TriggerCreateRequest(
                name=f"missing-env-{uuid.uuid4()}",
                type="cron",
                agent_id=agent.id,
                prompt_template="should not schedule missing env",
                cron_expr="*/5 * * * *",
                timezone="UTC",
                environment_ref=missing_ref,
            ),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "TRIGGER_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    triggers = (
        (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert triggers == []


@pytest.mark.asyncio
async def test_trigger_service_rejects_cross_project_agent_without_creating_trigger(db_session):
    _, project, _ = await _create_project_with_agent(db_session, name="TriggerSvcProjectA")
    _, other_project, other_agent = await _create_project_with_agent(db_session, name="TriggerSvcProjectB")

    with pytest.raises(AppError) as exc_info:
        await JoySafeterTriggerService(db_session).create(
            name=f"cross-agent-{uuid.uuid4()}",
            type="cron",
            agent_id=other_agent.id,
            prompt_template="must not bind to another project's agent",
            cron_expr="*/5 * * * *",
            timezone="UTC",
            project_id=project.id,
            org_id=project.org_id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "TRIGGER_AGENT_NOT_FOUND",
        "message": "Agent not found",
        "data": {"agent_id": str(other_agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    triggers = (
        (
            await db_session.execute(
                select(JoySafeterTrigger).where(JoySafeterTrigger.project_id.in_([project.id, other_project.id]))
            )
        )
        .scalars()
        .all()
    )
    assert triggers == []


@pytest.mark.asyncio
async def test_trigger_service_rejects_cross_project_environment_without_creating_trigger(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="TriggerSvcEnvProjectA")
    _, other_project, _ = await _create_project_with_agent(db_session, name="TriggerSvcEnvProjectB")
    other_env = await _create_environment(db_session, project=other_project)
    other_env_ref = f"env_{other_env.id}"

    with pytest.raises(AppError) as exc_info:
        await JoySafeterTriggerService(db_session).create(
            name=f"cross-env-{uuid.uuid4()}",
            type="cron",
            agent_id=agent.id,
            prompt_template="must not bind to another project's environment",
            cron_expr="*/5 * * * *",
            timezone="UTC",
            environment_ref=other_env_ref,
            project_id=project.id,
            org_id=project.org_id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "TRIGGER_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {other_env_ref}",
        "data": {"environment_ref": other_env_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    triggers = (
        (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert triggers == []


@pytest.mark.asyncio
async def test_create_trigger_rejects_archived_effective_environment_without_creating_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ArchivedTriggerEnv")
    env = await _create_environment(db_session, project=project, archived=True)
    env_ref = f"env_{env.id}"

    with pytest.raises(AppError) as exc_info:
        await create_trigger(
            _fake_request(),
            TriggerCreateRequest(
                name=f"archived-env-{uuid.uuid4()}",
                type="cron",
                agent_id=agent.id,
                prompt_template="should not schedule archived env",
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
    triggers = (
        (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert triggers == []


@pytest.mark.asyncio
async def test_manual_trigger_run_rejects_archived_environment_without_creating_task(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="TriggerArchivedEnv")
    env = await _create_environment(db_session, project=project)
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="trigger-archived-env")
    trigger.environment_ref = f"env_{env.id}"
    trigger_id = trigger.id
    env.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await run_trigger_now(trigger_id, db_session, _admin_ctx(project.id, org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: env_{env.id}",
        "data": {"environment_ref": f"env_{env.id}", "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    tasks = (
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)))
        .scalars()
        .all()
    )
    assert tasks == []


@pytest.mark.asyncio
async def test_update_trigger_rejects_missing_environment_without_persisting_ref(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="UpdateMissingEnv")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="update-missing-env")
    trigger_id = trigger.id
    missing_ref = f"env_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await update_trigger(
            _fake_request(),
            trigger_id,
            TriggerUpdateRequest(environment_ref=missing_ref),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "TRIGGER_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert row.environment_ref is None


@pytest.mark.asyncio
async def test_trigger_service_update_rejects_cross_project_environment_without_persisting_ref(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="TriggerSvcUpdateProjectA")
    _, other_project, _ = await _create_project_with_agent(db_session, name="TriggerSvcUpdateProjectB")
    other_env = await _create_environment(db_session, project=other_project)
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="svc-update-cross-env")
    trigger_id = trigger.id
    other_env_ref = f"env_{other_env.id}"

    with pytest.raises(AppError) as exc_info:
        await JoySafeterTriggerService(db_session).update(
            trigger_id,
            project.id,
            environment_ref=other_env_ref,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "TRIGGER_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {other_env_ref}",
        "data": {"environment_ref": other_env_ref},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert row.environment_ref is None


@pytest.mark.asyncio
async def test_update_trigger_rejects_duplicate_name_without_persisting_change(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="UpdateDuplicateName")
    existing = await _create_due_trigger(db_session, project=project, agent=agent, name="existing-name")
    target = await _create_due_trigger(db_session, project=project, agent=agent, name="target-name")
    target_id = target.id
    original_name = target.name

    with pytest.raises(AppError) as exc_info:
        await update_trigger(
            _fake_request(),
            target_id,
            TriggerUpdateRequest(name=existing.name),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "TRIGGER_NAME_EXISTS",
        "message": f"A trigger named '{existing.name}' already exists in this project",
        "data": {"name": existing.name},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == target_id))).scalar_one()
    assert row.name == original_name


@pytest.mark.asyncio
async def test_enable_trigger_rejects_archived_agent_without_rearming_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="EnableArchivedAgent")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="enable-archived-agent")
    trigger_id = trigger.id
    agent_id = agent.id
    trigger.enabled = False
    trigger.next_run_at = None
    agent.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await update_trigger(
            _fake_request(),
            trigger_id,
            TriggerUpdateRequest(enabled=True),
            db_session,
            _admin_ctx(project.id, org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new triggered runs.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert row.enabled is False
    assert row.next_run_at is None


@pytest.mark.asyncio
async def test_enable_trigger_rejects_archived_environment_without_rearming_trigger(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="EnableArchivedEnv")
    env = await _create_environment(db_session, project=project)
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="enable-archived-env")
    trigger_id = trigger.id
    trigger.environment_ref = f"env_{env.id}"
    trigger.enabled = False
    trigger.next_run_at = None
    env.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await update_trigger(
            _fake_request(),
            trigger_id,
            TriggerUpdateRequest(enabled=True),
            db_session,
            _admin_ctx(project.id, org.id),
        )

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
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert row.enabled is False
    assert row.next_run_at is None


@pytest.mark.asyncio
async def test_scheduler_advance_does_not_rearm_trigger_after_environment_archived_race(db_session):
    _, project, agent = await _create_project_with_agent(db_session, name="EnvAdvanceRace")
    env = await _create_environment(db_session, project=project)
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="env-advance-race")
    trigger.environment_ref = f"env_{env.id}"
    await db_session.commit()
    trigger_id = trigger.id

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="worker-before-env-archive",
        limit=1,
        lock_grace_sec=120,
    )
    assert [row.id for row in claimed] == [trigger_id]
    fired_slot = claimed[0].next_run_at
    assert fired_slot is not None

    env.archived_at = utc_now()
    await db_session.commit()
    await JoySafeterTriggerService(db_session).advance_after_fire(trigger_id, fired_slot)

    db_session.expire_all()
    paused_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert paused_trigger.enabled is True
    assert paused_trigger.next_run_at is None
    assert paused_trigger.locked_by is None
    assert paused_trigger.locked_at is None
    assert paused_trigger.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_advance_after_fire_catches_up_once_from_now_not_backfilling_missed_slots(db_session):
    # A trigger that came due long ago (worker was down) must advance to the NEXT
    # future cron boundary computed from *now*, firing the missed window exactly
    # once — not replay every missed slot. Backfill semantics (after=fired_slot)
    # would clamp next_run_at to ~now+1s (an unaligned instant); catch-up-once
    # lands on a real cron boundary (second==0, minute divisible by 5).
    _, project, agent = await _create_project_with_agent(db_session, name="CatchUpOnce")
    trigger = JoySafeterTrigger(
        name=f"catch-up-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=utc_now() - timedelta(hours=3),
        project_id=project.id,
        user_id="owner",
        org_id=project.org_id,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    fired_slot = trigger.next_run_at
    trigger_id = trigger.id

    await JoySafeterTriggerService(db_session).advance_after_fire(trigger_id, fired_slot)

    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert row.next_run_at is not None
    assert row.next_run_at > utc_now()
    # Landed on a real */5 boundary — proves it recomputed from now, not a clamped
    # backfill of the 3-hour-old slot.
    assert row.next_run_at.second == 0
    assert row.next_run_at.minute % 5 == 0
    assert row.last_fired_slot == fired_slot


@pytest.mark.asyncio
async def test_project_trigger_pause_clears_due_slots_and_resume_rearms_future(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ProjectTriggerPause")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="paused-cron")
    org_id = org.id
    project_id = project.id
    trigger_id = trigger.id

    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=True,
    )
    db_session.expire_all()
    paused_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert paused_trigger.next_run_at is None
    assert paused_trigger.locked_by is None
    assert paused_trigger.locked_at is None
    assert paused_trigger.config["next_run_at"] is None

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(worker_id="paused-worker", limit=10)
    assert [row.id for row in claimed] == []
    assert await JoySafeterTriggerService(db_session).earliest_next_run() is None

    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=False,
    )
    db_session.expire_all()
    resumed_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert resumed_trigger.next_run_at is not None
    assert resumed_trigger.next_run_at > utc_now()
    assert resumed_trigger.config["next_run_at"] == resumed_trigger.next_run_at.isoformat()


@pytest.mark.asyncio
async def test_project_trigger_pause_abandons_pending_retry_slot_before_resume(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ProjectTriggerPauseRetry")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="paused-retry-cron")
    org_id = org.id
    project_id = project.id
    trigger_id = trigger.id
    failed_slot = utc_now() - timedelta(minutes=15)
    trigger.pending_slot_at = failed_slot
    trigger.slot_attempts = 2
    trigger.next_run_at = utc_now() + timedelta(seconds=30)
    trigger.locked_by = "retry-worker"
    trigger.locked_at = utc_now()
    await db_session.commit()

    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=True,
    )
    db_session.expire_all()
    paused_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert paused_trigger.next_run_at is None
    assert paused_trigger.pending_slot_at is None
    assert paused_trigger.slot_attempts == 0
    assert paused_trigger.locked_by is None
    assert paused_trigger.locked_at is None

    before_resume = utc_now()
    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=False,
    )
    db_session.expire_all()
    resumed_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert resumed_trigger.pending_slot_at is None
    assert resumed_trigger.slot_attempts == 0
    assert resumed_trigger.next_run_at is not None
    assert resumed_trigger.next_run_at > before_resume
    assert resumed_trigger.next_run_at != failed_slot


@pytest.mark.asyncio
async def test_project_trigger_pause_resume_rearms_future_one_off_run_at(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="ProjectTriggerPauseOneOff")
    org_id = org.id
    project_id = project.id
    run_at = utc_now() + timedelta(hours=1)
    trigger = JoySafeterTrigger(
        name=f"paused-one-off-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="run once",
        cron_expr=None,
        run_at=run_at,
        timezone="UTC",
        enabled=True,
        next_run_at=run_at,
        project_id=project_id,
        user_id="trigger-owner",
        org_id=org_id,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    trigger_id = trigger.id

    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=True,
    )
    db_session.expire_all()
    paused_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert paused_trigger.next_run_at is None
    assert paused_trigger.config["next_run_at"] is None

    await ProjectService(db_session).update_project(
        project_id,
        org_id,
        triggers_paused=False,
    )
    db_session.expire_all()
    resumed_trigger = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id))
    ).scalar_one()
    assert resumed_trigger.next_run_at == run_at
    assert resumed_trigger.config["next_run_at"] == run_at.isoformat()


@pytest.mark.asyncio
async def test_updating_trigger_in_paused_project_does_not_rearm_next_run(db_session):
    org, project, agent = await _create_project_with_agent(db_session, name="PausedProjectTriggerUpdate")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="paused-update")
    trigger_id = trigger.id

    await ProjectService(db_session).update_project(
        project.id,
        org.id,
        triggers_paused=True,
    )

    updated = await JoySafeterTriggerService(db_session).update(
        trigger_id,
        project_id=project.id,
        cron_expr="*/2 * * * *",
    )

    assert updated is not None
    assert updated.next_run_at is None
    assert updated.config["next_run_at"] is None


@pytest.mark.asyncio
async def test_scheduled_task_cancel_does_not_mark_cancelled_when_runtime_relay_fails(db_session, monkeypatch):
    redis = _FakeCommandRedis(cancel_receivers=0)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )

    _, project, agent = await _create_project_with_agent(db_session, name="ReplaceRelayFail")
    trigger = await _create_due_trigger(db_session, project=project, agent=agent, name="replace-relay-fail")
    trigger.concurrency_policy = "replace"
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
        trigger_id=trigger.id,
        project_id=project.id,
        prompt="still running scheduled slot",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    trigger_id = trigger.id
    task_id = task.id
    session_id = session.id
    sandbox_id = sandbox.id

    with pytest.raises(AppError) as exc_info:
        await TaskCancellationService(db_session).cancel(
            task,
            reason=f"Replaced by trigger {trigger.id} slot {utc_now().isoformat()}",
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
        (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)))
        .scalars()
        .all()
    )
    assert [str(row.id) for row in tasks] == [str(task_id)]
    assert tasks[0].status == JoySafeterTaskStatus.RUNNING.value
