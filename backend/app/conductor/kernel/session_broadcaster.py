import asyncio
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SessionBroadcaster:
    def __init__(self, redis_client=None, instance_id: str = ""):
        self._channels: dict[uuid.UUID, list[asyncio.Queue]] = {}
        self._redis = redis_client
        self._instance_id = instance_id
        self._redis_tasks: dict[int, asyncio.Task] = {}

    async def broadcast(self, session_id: uuid.UUID, event: dict[str, Any]) -> None:
        if session_id in self._channels:
            for q in self._channels[session_id]:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        if self._redis:
            import json
            channel = f"conductor:session_events:{session_id}"
            wrapper = json.dumps({"source_instance": self._instance_id, "event": event})
            try:
                await self._redis.publish(channel, wrapper)
            except Exception as e:
                logger.warning("Failed to publish event to Redis: %s", e)

    def subscribe(self, session_id: uuid.UUID) -> asyncio.Queue:
        if session_id not in self._channels:
            self._channels[session_id] = []
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._channels[session_id].append(q)

        if self._redis:
            task = asyncio.create_task(
                self._redis_subscriber(session_id, q),
                name=f"redis-sub-{session_id}-{id(q)}",
            )
            self._redis_tasks[id(q)] = task

        return q

    def unsubscribe(self, session_id: uuid.UUID, q: asyncio.Queue) -> None:
        if session_id in self._channels:
            self._channels[session_id] = [
                x for x in self._channels[session_id] if x is not q
            ]
            if not self._channels[session_id]:
                del self._channels[session_id]

        task = self._redis_tasks.pop(id(q), None)
        if task and not task.done():
            task.cancel()

    async def _redis_subscriber(self, session_id: uuid.UUID, q: asyncio.Queue) -> None:
        import json
        pubsub = None
        try:
            pubsub = self._redis.pubsub()
            channel = f"conductor:session_events:{session_id}"
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                payload = json.loads(message["data"])
                if payload.get("source_instance") == self._instance_id:
                    continue
                try:
                    q.put_nowait(payload["event"])
                except asyncio.QueueFull:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Redis subscriber for session %s failed: %s", session_id, e)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
