from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.models.joysafeter_session import SessionStatus
from app.joysafeter_domain.services.agent_trigger_execution import AgentTriggerExecutor, AgentTriggerRunConfig
from app.joysafeter_shared.common.app_errors import AppError


pytestmark = pytest.mark.no_db


class _NoActiveTaskResult:
    def scalar_one_or_none(self):
        return None


class _FakeDb:
    async def execute(self, _stmt):
        return _NoActiveTaskResult()


class _FakeSubmission:
    def __init__(self, db):
        self.db = db

    async def enforce_admission(self, **_kwargs):
        return None

    async def create_and_dispatch(self, **kwargs):
        task = SimpleNamespace(id=uuid.uuid4(), status="pending", chat_session_id=kwargs["chat_session_id"])
        return task, True


def _agent(agent_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=agent_id or uuid.uuid4(),
        name="agent",
        version=1,
        environment_ref=None,
        env={},
        mcp_configs=[],
        skills=[],
        tools=[],
        agents=[],
        commands=[],
        permission_mode="bypassPermissions",
        metadata_={},
        multiagent=None,
        secret_ref=None,
    )


def _session(*, agent_id: uuid.UUID, status: str = SessionStatus.IDLE.value):
    return SimpleNamespace(id=uuid.uuid4(), agent_id=agent_id, status=status, archived_at=None)


def _config(agent, **overrides):
    values = dict(
        agent=agent,
        name="Daily",
        source="trigger:cron:test",
        prompt="run",
        system_prompt=None,
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
        schedule_id=uuid.uuid4(),
        metadata={"trigger_type": "cron"},
    )
    values.update(overrides)
    return AgentTriggerRunConfig(**values)


@pytest.fixture(autouse=True)
def patch_executor_dependencies(monkeypatch):
    state = {"sessions": {}, "created": []}

    class FakeSessionService:
        def __init__(self, db):
            self.db = db

        async def get_session(self, session_id, project_id=None):
            return state["sessions"].get(session_id)

        async def create_session(self, **kwargs):
            session = SimpleNamespace(
                id=uuid.uuid4(),
                agent_id=kwargs["agent_id"],
                status=SessionStatus.IDLE.value,
                archived_at=None,
                title=kwargs.get("title"),
                environment_ref=kwargs.get("environment_ref"),
                metadata_=kwargs.get("metadata") or {},
            )
            state["sessions"][session.id] = session
            state["created"].append(session)
            return session

    monkeypatch.setattr("app.joysafeter_domain.services.agent_trigger_execution.SessionService", FakeSessionService)
    monkeypatch.setattr("app.joysafeter_domain.services.agent_trigger_execution.TaskSubmissionService", _FakeSubmission)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.agent_trigger_execution.JoySafeterAgentService.build_execution_snapshot",
        lambda *args, **kwargs: {"snapshot": True},
    )
    return state


@pytest.mark.asyncio
async def test_fresh_mode_always_creates_new_session(patch_executor_dependencies):
    agent = _agent()
    reusable = _session(agent_id=agent.id)
    patch_executor_dependencies["sessions"][reusable.id] = reusable

    result = await AgentTriggerExecutor(_FakeDb()).run(
        _config(agent, session_mode="fresh", reusable_session_id=reusable.id),
    )

    assert result.session.id != reusable.id
    assert result.session.id == patch_executor_dependencies["created"][0].id
    assert result.task.chat_session_id == result.session.id


@pytest.mark.asyncio
async def test_reuse_mode_uses_idle_reusable_session(patch_executor_dependencies):
    agent = _agent()
    reusable = _session(agent_id=agent.id, status=SessionStatus.IDLE.value)
    patch_executor_dependencies["sessions"][reusable.id] = reusable

    result = await AgentTriggerExecutor(_FakeDb()).run(
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

    result = await AgentTriggerExecutor(_FakeDb()).run(
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

    result = await AgentTriggerExecutor(_FakeDb()).run(
        _config(agent, session_mode="pinned", pinned_session_id=pinned.id),
    )

    assert result.session.id == pinned.id
    assert patch_executor_dependencies["created"] == []
    assert result.task.chat_session_id == pinned.id


@pytest.mark.asyncio
async def test_pinned_mode_rejects_different_agent_session(patch_executor_dependencies):
    agent = _agent()
    pinned = _session(agent_id=uuid.uuid4(), status=SessionStatus.IDLE.value)
    patch_executor_dependencies["sessions"][pinned.id] = pinned

    with pytest.raises(AppError) as exc_info:
        await AgentTriggerExecutor(_FakeDb()).run(
            _config(agent, session_mode="pinned", pinned_session_id=pinned.id),
        )

    assert exc_info.value.code == "TRIGGER_PINNED_SESSION_AGENT_MISMATCH"
