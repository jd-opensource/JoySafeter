import asyncio
import uuid

import pytest

from app.joysafeter_api.api.v1.sessions import delete_session
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.orchestrator_bridge.session_broadcaster import SessionBroadcaster


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


class _BlockingPubSub:
    async def subscribe(self, channel):  # noqa: ANN001
        return None

    async def listen(self):
        # Mimic a real Redis subscriber blocked waiting for messages: never
        # yields, so the _redis_subscriber task stays alive until cancelled.
        await asyncio.Event().wait()
        yield  # pragma: no cover - unreachable

    async def unsubscribe(self):
        return None

    async def close(self):
        return None


class _FakeRedis:
    def pubsub(self):
        return _BlockingPubSub()

    async def publish(self, channel, message):  # noqa: ANN001
        return 0


async def _idle_session(db_session) -> JoySafeterSession:
    agent = JoySafeterAgent(name=f"del-sess-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest.mark.asyncio
async def test_delete_session_cancels_redis_subscriber_tasks(db_session, monkeypatch):
    session = await _idle_session(db_session)
    session_id = session.id
    # The broadcaster keys its internal maps by the physical UUID (the
    # cross-language Redis channel contract), so assert against that form.
    raw_session_id = session.id.uuid

    broadcaster = SessionBroadcaster(redis_client=_FakeRedis(), instance_id="test-instance")
    monkeypatch.setattr(
        "app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster",
        lambda: broadcaster,
    )

    # A live SSE consumer subscribes, spawning a tracked Redis subscriber task.
    broadcaster.subscribe(session_id)
    await asyncio.sleep(0)  # let the subscriber task start
    task = broadcaster._redis_tasks[raw_session_id]
    assert not task.done()

    result = await delete_session(session_id, db_session, _auth_ctx())
    assert result["deleted"] is True

    await asyncio.sleep(0)  # let cancellation propagate

    # The subscriber task and its bookkeeping must be cleaned up, not leaked.
    assert raw_session_id not in broadcaster._redis_tasks
    assert task.cancelled() or task.done()
    assert raw_session_id not in broadcaster._channels


class _FakeRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_sse_stream_delivers_event_published_during_replay(db_session, monkeypatch):
    """An event published in the replay->subscribe handoff window must still be
    pushed live. Subscribing before replay buffers it in the queue; the old
    subscribe-after-replay order dropped it (recovered only via 30s DB tick)."""
    from app.joysafeter_api.api.v1 import sessions as sessions_module

    session = await _idle_session(db_session)
    session_id = session.id

    broadcaster = SessionBroadcaster(redis_client=_FakeRedis(), instance_id="test-instance")
    monkeypatch.setattr(
        "app.joysafeter_shared.orchestrator_bridge.get_session_broadcaster",
        lambda: broadcaster,
    )

    injected = {"done": False}

    async def replay_injects_live_event(self, sid, limit, after, project_id=None):  # noqa: ANN001
        # Simulate an event landing while the replay query is in flight.
        if not injected["done"]:
            injected["done"] = True
            await broadcaster.send(
                sid,
                {"type": "agent.message", "seq": 5, "id": "evt_live", "text": "hi"},
            )
        return [], False

    monkeypatch.setattr(sessions_module.SessionService, "list_events", replay_injects_live_event)

    response = await sessions_module.session_event_stream(
        _FakeRequest(),
        session_id,
        0,  # after_seq -> replay path runs
        db_session,
        _auth_ctx(),
    )

    agen = response.body_iterator
    try:
        chunk = await asyncio.wait_for(agen.__anext__(), timeout=3)
    finally:
        await agen.aclose()

    assert "evt_live" in chunk
    assert '"seq": 5' in chunk
