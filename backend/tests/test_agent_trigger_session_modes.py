from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.triggers.execution_service import AgentTriggerExecutor, AgentTriggerRunConfig
from app.joysafeter_domain.models.joysafeter_session import SessionStatus
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import AgentId, SessionId, TaskId

pytestmark = pytest.mark.no_db


class _NoActiveTaskResult:
    def scalar_one_or_none(self):
        return None


class _TriggerLockResult:
    def scalar_one_or_none(self):
        return uuid.uuid4()


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, *, keyed_session=None, with_trigger_lock=True):
        self.execute_count = 0
        self.keyed_session = keyed_session
        self.with_trigger_lock = with_trigger_lock

    async def execute(self, _stmt):
        self.execute_count += 1
        if self.with_trigger_lock and self.execute_count in {1, 3}:
            return _TriggerLockResult()
        keyed_lookup_call = 2 if self.with_trigger_lock else 1
        if self.keyed_session is not None and self.execute_count == keyed_lookup_call:
            return _ScalarResult(self.keyed_session)
        return _NoActiveTaskResult()


class _FakeSubmission:
    last_kwargs = None

    def __init__(self, db):
        self.db = db

    async def enforce_admission(self, **_kwargs):
        return None

    async def create_and_dispatch(self, **kwargs):
        type(self).last_kwargs = kwargs
        task = SimpleNamespace(id=TaskId.new(), status="pending", chat_session_id=kwargs["chat_session_id"])
        return task, True


def _agent(agent_id: AgentId | None = None):
    return SimpleNamespace(
        id=agent_id or AgentId.new(),
        name="agent",
        version=1,
        environment_ref=None,
        env={},
        mcp_servers=[],
        skills=[],
        tools=[],
        agents=[],
        commands=[],
        permission_mode="bypassPermissions",
        metadata_={},
        multiagent=None,
        secret_ref=None,
    )


def _session(
    *,
    agent_id: AgentId,
    status: str = SessionStatus.IDLE.value,
    environment_ref: str | None = None,
    metadata: dict | None = None,
):
    return SimpleNamespace(
        id=SessionId.new(),
        agent_id=agent_id,
        status=status,
        archived_at=None,
        environment_ref=environment_ref,
        metadata_=metadata or {},
    )


def _config(agent, **overrides):
    values = dict(
        agent=agent,
        name="Daily",
        source="trigger:cron:test",
        prompt="run",
        environment_ref=None,
        timeout_sec=7200,
        max_retries=2,
        project_id="project-a",
        user_id="user-a",
        org_id="org-a",
        idempotency_key=f"test:{uuid.uuid4()}",
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
        trigger_id=uuid.uuid4(),
        metadata={"trigger_type": "cron"},
    )
    values.update(overrides)
    return AgentTriggerRunConfig(**values)


@pytest.fixture(autouse=True)
def patch_executor_dependencies(monkeypatch):
    _FakeSubmission.last_kwargs = None
    state = {
        "sessions": {},
        "created": [],
        "environments": {},
        "environment_lookups": [],
        "audit_actors": [],
    }

    class FakeSessionService:
        def __init__(self, db):
            self.db = db

        async def get_session(self, session_id, project_id=None):
            return state["sessions"].get(session_id)

    class FakeSessionCreationService:
        def __init__(self, db, *, audit_actor):
            self.db = db
            state["audit_actors"].append(audit_actor)

        async def create_from_source(self, command):
            session = SimpleNamespace(
                id=SessionId.new(),
                agent_id=command.agent_id,
                status=SessionStatus.IDLE.value,
                archived_at=None,
                title=command.title,
                environment_ref=command.environment_ref,
                metadata_=dict(command.metadata or {}),
            )
            state["sessions"][session.id] = session
            state["created"].append(session)
            return session

    class FakeEnvironmentService:
        def __init__(self, db):
            self.db = db

        async def get_environment_by_ref(self, environment_ref, project_id=None):
            state["environment_lookups"].append((environment_ref, project_id))
            environment = state["environments"].get(environment_ref)
            if environment is None or environment.deleted_at is not None:
                return None
            if project_id is not None and environment.project_id != project_id:
                return None
            return environment

    monkeypatch.setattr("app.joysafeter_application.triggers.execution_service.SessionService", FakeSessionService)
    monkeypatch.setattr(
        "app.joysafeter_application.triggers.execution_service.SessionCreationService",
        FakeSessionCreationService,
    )
    monkeypatch.setattr(
        "app.joysafeter_application.triggers.execution_service.EnvironmentService",
        FakeEnvironmentService,
    )
    monkeypatch.setattr(
        "app.joysafeter_application.triggers.execution_service.TaskSubmissionService",
        _FakeSubmission,
    )
    return state


@pytest.mark.asyncio
async def test_legacy_trigger_system_prompt_is_forwarded(patch_executor_dependencies):
    agent = _agent()

    await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
        _config(agent, system_prompt="Preserve legacy instructions"),
    )

    assert _FakeSubmission.last_kwargs["system_prompt"] == "Preserve legacy instructions"


@pytest.mark.asyncio
async def test_fresh_mode_always_creates_new_session(patch_executor_dependencies):
    agent = _agent()
    reusable = _session(agent_id=agent.id)
    patch_executor_dependencies["sessions"][reusable.id] = reusable

    result = await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
        _config(agent, session_mode="fresh", reusable_session_id=reusable.id),
    )

    assert result.session.id != reusable.id
    assert result.session.id == patch_executor_dependencies["created"][0].id
    assert result.task.chat_session_id == result.session.id
    assert patch_executor_dependencies["audit_actors"] == [CredentialAuditActor.system("test")]


@pytest.mark.asyncio
async def test_reuse_mode_uses_idle_reusable_session(patch_executor_dependencies):
    agent = _agent()
    reusable = _session(agent_id=agent.id, status=SessionStatus.IDLE.value)
    patch_executor_dependencies["sessions"][reusable.id] = reusable

    result = await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
        _config(agent, session_mode="reuse", reusable_session_id=reusable.id),
    )

    assert result.session.id == reusable.id
    assert patch_executor_dependencies["created"] == []
    assert result.task.chat_session_id == reusable.id


@pytest.mark.asyncio
async def test_reuse_mode_creates_session_when_reusable_is_busy(patch_executor_dependencies):
    agent = _agent()
    reusable = _session(agent_id=agent.id, status=SessionStatus.RUNNING.value)
    patch_executor_dependencies["sessions"][reusable.id] = reusable

    result = await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
        _config(agent, session_mode="reuse", reusable_session_id=reusable.id),
    )

    assert result.session.id != reusable.id
    assert result.session.id == patch_executor_dependencies["created"][0].id
    assert result.task.chat_session_id == result.session.id


@pytest.mark.asyncio
async def test_pinned_mode_uses_selected_idle_session(patch_executor_dependencies):
    agent = _agent()
    pinned = _session(agent_id=agent.id, status=SessionStatus.IDLE.value)
    patch_executor_dependencies["sessions"][pinned.id] = pinned

    result = await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
        _config(agent, session_mode="pinned", pinned_session_id=pinned.id),
    )

    assert result.session.id == pinned.id
    assert patch_executor_dependencies["created"] == []
    assert result.task.chat_session_id == pinned.id


@pytest.mark.asyncio
async def test_pinned_mode_rejects_different_agent_session(patch_executor_dependencies):
    agent = _agent()
    pinned = _session(agent_id=AgentId.new(), status=SessionStatus.IDLE.value)
    patch_executor_dependencies["sessions"][pinned.id] = pinned

    with pytest.raises(AppError) as exc_info:
        await AgentTriggerExecutor(_FakeDb(), audit_actor=CredentialAuditActor.system("test")).run(
            _config(agent, session_mode="pinned", pinned_session_id=pinned.id),
        )

    assert exc_info.value.code == "TRIGGER_PINNED_SESSION_AGENT_MISMATCH"


@pytest.mark.parametrize("session_mode", ["pinned", "reuse", "keyed"])
@pytest.mark.parametrize(
    ("binding_state", "expected_code"),
    [
        ("missing", "SESSION_ENVIRONMENT_NOT_FOUND"),
        ("deleted", "SESSION_ENVIRONMENT_NOT_FOUND"),
        ("archived", "ENVIRONMENT_ARCHIVED"),
        ("cross_project", "SESSION_ENVIRONMENT_NOT_FOUND"),
    ],
)
@pytest.mark.asyncio
async def test_reused_session_explicit_invalid_environment_binding_fails_closed(
    patch_executor_dependencies,
    session_mode,
    binding_state,
    expected_code,
):
    agent = _agent()
    agent.environment_ref = "live-environment"
    patch_executor_dependencies["environments"]["live-environment"] = SimpleNamespace(
        id="live-environment-id",
        project_id="project-a",
        archived_at=None,
        deleted_at=None,
    )

    invalid_ref = f"{binding_state}-environment"
    if binding_state != "missing":
        patch_executor_dependencies["environments"][invalid_ref] = SimpleNamespace(
            id=f"{binding_state}-environment-id",
            project_id="project-b" if binding_state == "cross_project" else "project-a",
            archived_at=object() if binding_state == "archived" else None,
            deleted_at=object() if binding_state == "deleted" else None,
        )

    reused = _session(
        agent_id=agent.id,
        environment_ref=invalid_ref,
        metadata={"trigger_session_key": "alpha"},
    )
    patch_executor_dependencies["sessions"][reused.id] = reused
    db = _FakeDb(keyed_session=reused if session_mode == "keyed" else None, with_trigger_lock=False)
    config_overrides = {
        "session_mode": session_mode,
        "environment_ref": "live-environment",
        "trigger_id": None,
        "session_key": "alpha" if session_mode == "keyed" else None,
        "pinned_session_id": reused.id if session_mode == "pinned" else None,
        "reusable_session_id": reused.id if session_mode == "reuse" else None,
    }

    with pytest.raises(AppError) as exc_info:
        await AgentTriggerExecutor(db, audit_actor=CredentialAuditActor.system("test")).run(
            _config(agent, **config_overrides)
        )

    assert exc_info.value.code == expected_code
    assert patch_executor_dependencies["environment_lookups"] == [(invalid_ref, "project-a")]
    assert patch_executor_dependencies["created"] == []
    assert _FakeSubmission.last_kwargs is None


@pytest.mark.parametrize("session_mode", ["pinned", "reuse", "keyed"])
@pytest.mark.asyncio
async def test_reused_session_without_environment_binding_keeps_existing_fallback(
    patch_executor_dependencies,
    session_mode,
):
    agent = _agent()
    agent.environment_ref = "live-environment"
    reused = _session(
        agent_id=agent.id,
        environment_ref=None,
        metadata={"trigger_session_key": "alpha"},
    )
    patch_executor_dependencies["sessions"][reused.id] = reused
    db = _FakeDb(keyed_session=reused if session_mode == "keyed" else None, with_trigger_lock=False)

    result = await AgentTriggerExecutor(db, audit_actor=CredentialAuditActor.system("test")).run(
        _config(
            agent,
            session_mode=session_mode,
            environment_ref="live-environment",
            trigger_id=None,
            session_key="alpha" if session_mode == "keyed" else None,
            pinned_session_id=reused.id if session_mode == "pinned" else None,
            reusable_session_id=reused.id if session_mode == "reuse" else None,
        )
    )

    assert result.session.id == reused.id
    assert patch_executor_dependencies["environment_lookups"] == []
    assert patch_executor_dependencies["created"] == []
    assert _FakeSubmission.last_kwargs["chat_session_id"] == reused.id
