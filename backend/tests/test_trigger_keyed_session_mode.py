"""keyed session mode: reuse the key's idle session, else create one stamped with it."""

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.models.joysafeter_session import SessionStatus
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    render_session_key,
)

pytestmark = pytest.mark.no_db


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _SequencedDb:
    """execute() returns the keyed-lookup result first, then None (active-task check)."""

    def __init__(self, keyed_session=None):
        self._keyed_session = keyed_session
        self._calls = 0

    async def execute(self, _stmt):
        self._calls += 1
        if self._calls == 1:
            return _Result(self._keyed_session)
        return _Result(None)


def _agent():
    return SimpleNamespace(id=uuid.uuid4(), name="agent", version=1, environment_ref=None)


def _config(agent, **over):
    values = dict(
        agent=agent,
        name="Hook",
        source="trigger:webhook:test",
        prompt="run",
        environment_ref=None,
        timeout_sec=7200,
        max_retries=2,
        project_id="project-a",
        user_id="user-a",
        org_id="org-a",
        idempotency_key=f"test:{uuid.uuid4()}",
        session_mode="keyed",
        session_key="alpha",
        metadata={"trigger_type": "webhook"},
    )
    values.update(over)
    return AgentTriggerRunConfig(**values)


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    state = {"created": []}

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def get_session(self, session_id, project_id=None):
            return None

        async def create_session_from_source(self, command):
            session = SimpleNamespace(
                id=uuid.uuid4(),
                agent_id=command.agent_id,
                status=SessionStatus.IDLE.value,
                archived_at=None,
                metadata_=dict(command.metadata or {}),
            )
            state["created"].append(session)
            return session

    monkeypatch.setattr("app.joysafeter_domain.services.agent_trigger_execution.SessionService", FakeSessionService)
    return state


@pytest.mark.asyncio
async def test_keyed_reuses_session_matching_the_key(patch_deps):
    agent = _agent()
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent.id,
        status=SessionStatus.IDLE.value,
        archived_at=None,
        metadata_={"trigger_session_key": "alpha"},
    )
    executor = AgentTriggerExecutor(_SequencedDb(keyed_session=existing))
    session, created = await executor.resolve_session(_config(agent, session_key="alpha"))
    assert created is False
    assert session.id == existing.id
    assert patch_deps["created"] == []


@pytest.mark.asyncio
async def test_keyed_creates_new_session_stamped_with_key_on_miss(patch_deps):
    agent = _agent()
    executor = AgentTriggerExecutor(_SequencedDb(keyed_session=None))
    session, created = await executor.resolve_session(_config(agent, session_key="beta"))
    assert created is True
    assert session.metadata_.get("trigger_session_key") == "beta"
    assert len(patch_deps["created"]) == 1


def test_rendered_keyed_session_key_is_trimmed_and_bounded():
    rendered = render_session_key("customer:{{ body.customer_id }}", {"body": {"customer_id": "x" * 10_000}})

    assert rendered is not None
    assert rendered.startswith("customer:")
    assert len(rendered) <= 512


@pytest.mark.asyncio
async def test_keyed_executor_bounds_direct_config_session_key_on_miss(patch_deps):
    agent = _agent()
    executor = AgentTriggerExecutor(_SequencedDb(keyed_session=None))
    session, created = await executor.resolve_session(_config(agent, session_key=" y" * 10_000))

    assert created is True
    assert len(session.metadata_.get("trigger_session_key")) <= 512
