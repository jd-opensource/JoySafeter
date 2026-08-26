"""Server-derived idempotency for task submission.

A client that omits ``Idempotency-Key`` must still be protected against an
accidental double-submit (double-click, proxy retry, flaky-network retry) firing
the same real task — and therefore the same real pentest tooling — twice. The
server derives a short-window fallback key from the request identity so that
near-simultaneous identical submits collapse to one task, while a deliberate
re-run in a later window still creates a fresh task.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.joysafeter_api.api.v1 import tasks as tasks_module
from app.joysafeter_api.api.v1.tasks import create_task
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, OrganizationId, UserId

TEST_USER_ID = UserId.new()
TEST_ORGANIZATION_ID = OrganizationId.new()


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=TEST_ORGANIZATION_ID,
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _make_agent(db_session) -> JoySafeterAgent:
    agent = JoySafeterAgent(id=AgentId.new(), name=f"auto-idem-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_double_submit_without_idempotency_key_creates_one_task(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    # Pin the debounce window so the test exercises "two submits in the same
    # window" deterministically instead of depending on wall-clock timing.
    monkeypatch.setattr(tasks_module, "_auto_idempotency_window_bucket", lambda: 424242)
    agent = await _make_agent(db_session)

    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target once")
    first = await create_task(req, db_session, _auth_ctx())
    second = await create_task(req, db_session, _auth_ctx())

    assert first.id == second.id, "accidental resubmit without a key must collapse to one task"
    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent.id)
    )
    assert total == 1
    assert redis.rpushed == [("joysafeter:global_queue", str(first.id.uuid))], "the task must be enqueued exactly once"


@pytest.mark.asyncio
async def test_different_prompt_without_key_creates_distinct_tasks(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    agent = await _make_agent(db_session)

    first = await create_task(
        JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target A"), db_session, _auth_ctx()
    )
    second = await create_task(
        JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="scan target B"), db_session, _auth_ctx()
    )

    assert first.id != second.id, "different submissions must not be deduped by the fallback key"
    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent.id)
    )
    assert total == 2


@pytest.mark.asyncio
async def test_identical_submit_in_a_later_window_creates_a_fresh_task(db_session, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    agent = await _make_agent(db_session)
    req = JoySafeterCreateTaskRequest(agent_id=agent.id, prompt="rerun me")

    monkeypatch.setattr(tasks_module, "_auto_idempotency_window_bucket", lambda: 1000)
    first = await create_task(req, db_session, _auth_ctx())

    # A deliberate re-run once the debounce window has elapsed must NOT be
    # swallowed — it lands in a new bucket and creates a fresh task.
    monkeypatch.setattr(tasks_module, "_auto_idempotency_window_bucket", lambda: 1001)
    second = await create_task(req, db_session, _auth_ctx())

    assert first.id != second.id, "a re-run in a later window must create a new task"
    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent.id)
    )
    assert total == 2
