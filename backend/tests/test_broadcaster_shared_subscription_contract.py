"""Many SSE viewers of one session must share ONE Redis subscription.

subscribe() previously spawned a separate _redis_subscriber task — each opening
its own Redis pubsub connection to the same channel — per subscriber queue. N
viewers of one session then meant N redundant Redis subscriptions per instance
(connection amplification). One shared subscriber per session must fan every
remote event out to all local queues, and be torn down only when the last
subscriber leaves.
"""

import asyncio
import json
import uuid

import pytest

from app.joysafeter_shared.orchestrator_bridge.session_broadcaster import SessionBroadcaster

pytestmark = pytest.mark.no_db


class _OneMessagePubSub:
    def __init__(self, message: str):
        self._message = message

    async def subscribe(self, channel):
        return None

    async def listen(self):
        yield {"type": "message", "data": self._message}
        await asyncio.Event().wait()  # then block like a real idle subscriber

    async def unsubscribe(self):
        return None

    async def close(self):
        return None


class _CountingRedis:
    def __init__(self, message: str):
        self.pubsub_calls = 0
        self._message = message

    def pubsub(self):
        self.pubsub_calls += 1
        return _OneMessagePubSub(self._message)

    async def publish(self, channel, message):
        return 0


def _remote_event() -> str:
    return json.dumps(
        {"source_instance": "other-instance", "event": {"type": "agent.message", "seq": 7, "id": "evt_x"}}
    )


@pytest.mark.asyncio
async def test_multiple_subscribers_share_one_redis_subscription():
    redis = _CountingRedis(_remote_event())
    b = SessionBroadcaster(redis_client=redis, instance_id="me")
    sid = uuid.uuid4()

    q1 = b.subscribe(sid)
    q2 = b.subscribe(sid)
    await asyncio.sleep(0.05)

    assert redis.pubsub_calls == 1, "N subscribers of one session must share ONE Redis subscription"
    assert len(b._redis_tasks) == 1

    # The single shared subscriber must fan the remote event out to BOTH queues.
    ev1 = await asyncio.wait_for(q1.get(), timeout=1)
    ev2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert ev1["id"] == "evt_x"
    assert ev2["id"] == "evt_x"


@pytest.mark.asyncio
async def test_shared_subscriber_torn_down_only_on_last_unsubscribe():
    redis = _CountingRedis(_remote_event())
    b = SessionBroadcaster(redis_client=redis, instance_id="me")
    sid = uuid.uuid4()

    q1 = b.subscribe(sid)
    q2 = b.subscribe(sid)
    await asyncio.sleep(0)

    b.unsubscribe(sid, q1)
    assert sid in b._redis_tasks, "subscriber must stay alive while another viewer remains"

    b.unsubscribe(sid, q2)
    await asyncio.sleep(0)
    assert sid not in b._redis_tasks, "subscriber must be torn down when the last viewer leaves"
