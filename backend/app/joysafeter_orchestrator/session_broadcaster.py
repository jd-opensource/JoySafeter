import asyncio
import json
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SessionBroadcaster:
    """Broadcast session events to local subscribers and cross-instance via Redis.

    Matches SessionEventBroadcaster from joysafeter-kernel/src/session_broadcast.rs.

    Rust semantics:
    - channels map: session_id -> list of subscriber queues
    - broadcast::channel capacity = 256
    - subscribe() returns a receiver and starts a Redis subscriber task
    - send() broadcasts locally AND publishes to Redis
    - remove() drops all subscribers for a session
    """

    def __init__(self, redis_client=None, instance_id: str = ""):
        self._channels: dict[uuid.UUID, list[asyncio.Queue]] = {}
        self._redis = redis_client
        self._instance_id = instance_id
        self._redis_tasks: dict[int, asyncio.Task] = {}

    def subscribe(self, session_id: uuid.UUID) -> asyncio.Queue:
        """Subscribe to events for a session. Returns an asyncio.Queue.

        Matches Rust's subscribe() which returns broadcast::Receiver<SessionEvent>.
        Also spawns a Redis subscriber to inject remote events into the local queue.
        """
        if session_id not in self._channels:
            self._channels[session_id] = []
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._channels[session_id].append(q)

        # Start Redis subscriber to inject remote events into local channel
        if self._redis:
            task = asyncio.create_task(
                self._redis_subscriber(session_id, q),
                name=f"redis-sub-{session_id}-{id(q)}",
            )
            self._redis_tasks[id(q)] = task

        return q

    async def send(self, session_id: uuid.UUID, event: dict[str, Any]) -> None:
        """Send an event to all local subscribers and publish to Redis.

        Matches Rust's send() method. Rust signature:
            pub fn send(&self, session_id: Uuid, event: SessionEvent)
        Note: async in Python for ergonomic awaiting by callers; Rust version is
        sync but spawns a tokio task for Redis publish.
        """
        if session_id in self._channels:
            local_event = {**event, "_sse_source": event.get("_sse_source") or "local_broadcast"}
            for q in self._channels[session_id]:
                try:
                    q.put_nowait(local_event)
                except asyncio.QueueFull:
                    pass

        # Publish to Redis for cross-instance delivery
        if self._redis:
            channel = f"joysafeter:session_events:{session_id}"
            wrapper = json.dumps({"source_instance": self._instance_id, "event": event})
            asyncio.create_task(self._publish_to_redis(channel, wrapper))

    def remove(self, session_id: uuid.UUID) -> None:
        """Remove all subscribers for a session.

        Matches Rust's remove() method which drops the channel entry.
        """
        queues = self._channels.pop(session_id, [])
        # Cancel any Redis subscriber tasks associated with removed queues
        for q in queues:
            task = self._redis_tasks.pop(id(q), None)
            if task and not task.done():
                task.cancel()

    def unsubscribe(self, session_id: uuid.UUID, q: asyncio.Queue) -> None:
        """Remove a single subscriber queue. (Extra Python convenience method.)"""
        if session_id in self._channels:
            self._channels[session_id] = [
                x for x in self._channels[session_id] if x is not q
            ]
            if not self._channels[session_id]:
                del self._channels[session_id]

        task = self._redis_tasks.pop(id(q), None)
        if task and not task.done():
            task.cancel()

    async def _publish_to_redis(self, channel: str, wrapper: str) -> None:
        try:
            await self._redis.publish(channel, wrapper)
        except Exception as e:
            logger.warning("Failed to publish event to Redis: %s", e)

    async def _redis_subscriber(self, session_id: uuid.UUID, q: asyncio.Queue) -> None:
        backoff = 1
        max_backoff = 30
        while True:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                channel = f"joysafeter:session_events:{session_id}"
                await pubsub.subscribe(channel)
                backoff = 1
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    payload = json.loads(message["data"])
                    if payload.get("source_instance") == self._instance_id:
                        continue
                    try:
                        event = payload["event"]
                        if isinstance(event, dict):
                            event = {**event, "_sse_source": "redis_pubsub"}
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "Redis subscriber for session %s failed: %s, reconnecting in %ds",
                    session_id, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            finally:
                if pubsub:
                    try:
                        await pubsub.unsubscribe()
                        await pubsub.close()
                    except Exception:
                        pass
