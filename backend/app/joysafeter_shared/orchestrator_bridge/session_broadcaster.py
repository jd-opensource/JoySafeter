import asyncio
import json
import logging
from typing import Any

from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.ids import SessionId

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
        self._channels: dict[SessionId, list[asyncio.Queue]] = {}
        self._redis = redis_client
        self._instance_id = instance_id
        # One shared Redis subscriber task per session (NOT per queue), so N local
        # viewers of a session share a single Redis pubsub subscription instead of
        # opening N redundant ones (connection amplification).
        self._redis_tasks: dict[SessionId, asyncio.Task] = {}

    def subscribe(self, session_id: SessionId) -> asyncio.Queue:
        """Subscribe to events for a session. Returns an asyncio.Queue.

        Matches Rust's subscribe() which returns broadcast::Receiver<SessionEvent>.
        The first subscriber for a session starts ONE shared Redis subscriber that
        fans remote events out to every local queue; later subscribers reuse it.
        """
        if session_id not in self._channels:
            self._channels[session_id] = []
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._channels[session_id].append(q)

        # Start the shared Redis subscriber once per session.
        if self._redis and session_id not in self._redis_tasks:
            task = asyncio.create_task(
                self._redis_subscriber(session_id),
                name=f"redis-sub-{session_id}",
            )
            self._redis_tasks[session_id] = task

        return q

    async def send(self, session_id: SessionId, event: dict[str, Any]) -> None:
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
                    # Signal the client that events were dropped so it can reconnect
                    # and replay from DB. Drain and inject a lagged marker.
                    try:
                        while not q.empty():
                            q.get_nowait()
                        q.put_nowait({"lagged": True})
                    except Exception as exc:
                        logger.warning(
                            "Failed to signal lagged session subscriber",
                            extra={
                                "error": async_boundary_error_payload(
                                    code="SESSION_BROADCAST_LAG_SIGNAL_FAILED",
                                    message="Failed to signal lagged session subscriber",
                                    boundary="session_broadcaster",
                                    operation="local_lag_signal",
                                    data={"session_id": str(session_id)},
                                    detail=exc.__class__.__name__,
                                )
                            },
                            exc_info=True,
                        )

        # Publish to Redis for cross-instance delivery
        if self._redis:
            channel = f"joysafeter:session_events:{session_id.uuid}"
            wrapper = json.dumps({"source_instance": self._instance_id, "event": event})
            asyncio.create_task(self._publish_to_redis(channel, wrapper))

    def remove(self, session_id: SessionId) -> None:
        """Remove all subscribers for a session.

        Matches Rust's remove() method which drops the channel entry.
        """
        self._channels.pop(session_id, None)
        task = self._redis_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    def unsubscribe(self, session_id: SessionId, q: asyncio.Queue) -> None:
        """Remove a single subscriber queue. (Extra Python convenience method.)

        The shared Redis subscriber is torn down only when the LAST queue for the
        session is removed, so remaining viewers keep receiving remote events.
        """
        remaining = self._channels.get(session_id)
        if remaining is not None:
            self._channels[session_id] = [x for x in remaining if x is not q]
            if not self._channels[session_id]:
                del self._channels[session_id]
                task = self._redis_tasks.pop(session_id, None)
                if task and not task.done():
                    task.cancel()

    async def _publish_to_redis(self, channel: str, wrapper: str) -> None:
        try:
            await self._redis.publish(channel, wrapper)
        except Exception as e:
            session_id = channel.rsplit(":", 1)[-1]
            logger.warning(
                "Failed to publish session event to Redis",
                extra={
                    "error": async_boundary_error_payload(
                        code="SESSION_BROADCAST_REDIS_PUBLISH_FAILED",
                        message="Failed to publish session event to Redis",
                        boundary="session_broadcaster",
                        operation="redis_publish",
                        data={"channel": channel, "session_id": session_id},
                        detail=e.__class__.__name__,
                    )
                },
                exc_info=True,
            )

    async def _redis_subscriber(self, session_id: SessionId) -> None:
        backoff = 1
        max_backoff = 30
        while True:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                channel = f"joysafeter:session_events:{session_id.uuid}"
                await pubsub.subscribe(channel)
                backoff = 1
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    payload = json.loads(message["data"])
                    if payload.get("source_instance") == self._instance_id:
                        continue
                    event = payload["event"]
                    if isinstance(event, dict):
                        event = {**event, "_sse_source": "redis_pubsub"}
                    # Fan the remote event out to every local subscriber of this
                    # session (snapshot the list — unsubscribe may mutate it).
                    for q in list(self._channels.get(session_id, [])):
                        try:
                            q.put_nowait(event)
                        except asyncio.QueueFull:
                            # Drain queue and signal lag so this client reconnects
                            try:
                                while not q.empty():
                                    q.get_nowait()
                                q.put_nowait({"lagged": True})
                            except Exception as exc:
                                logger.warning(
                                    "Failed to signal lagged Redis session subscriber",
                                    extra={
                                        "error": async_boundary_error_payload(
                                            code="SESSION_BROADCAST_LAG_SIGNAL_FAILED",
                                            message="Failed to signal lagged Redis session subscriber",
                                            boundary="session_broadcaster",
                                            operation="redis_lag_signal",
                                            data={"session_id": str(session_id)},
                                            detail=exc.__class__.__name__,
                                        )
                                    },
                                    exc_info=True,
                                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                error_payload = async_boundary_error_payload(
                    code="SESSION_BROADCAST_REDIS_SUBSCRIBE_FAILED",
                    message="Redis session event subscriber failed",
                    boundary="session_broadcaster",
                    operation="redis_subscribe",
                    data={"session_id": str(session_id), "backoff_seconds": backoff},
                    detail=e.__class__.__name__,
                )
                logger.warning(
                    "Redis subscriber for session %s failed: %s, reconnecting in %ds",
                    session_id,
                    e,
                    backoff,
                    extra={"error": error_payload},
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
