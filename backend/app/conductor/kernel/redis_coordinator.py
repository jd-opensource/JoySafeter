"""Cross-instance HA coordination via Redis.

Ported from agentd/crates/conductor-store/src/redis_coord.rs.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

RELEASE_IF_OWNER_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

REFRESH_IF_OWNER_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""


class RedisCoordinator:
    def __init__(self, redis_client, instance_id: str):
        self._redis = redis_client
        self.instance_id = instance_id
        self._heartbeat_task: Optional[asyncio.Task] = None

    # --- Instance Registry ---

    async def register_instance(
        self, grpc_addr: str = "", http_addr: str = ""
    ) -> None:
        key = f"conductor:instances:{self.instance_id}"
        pipe = self._redis.pipeline()
        pipe.hset(
            key,
            mapping={
                "grpc_addr": grpc_addr,
                "http_addr": http_addr,
                "started_at": str(int(time.time())),
            },
        )
        pipe.expire(key, 30)
        await pipe.execute()

    async def heartbeat(self) -> None:
        key = f"conductor:instances:{self.instance_id}"
        await self._redis.expire(key, 30)

    def spawn_heartbeat(self) -> asyncio.Task:
        async def _loop():
            while True:
                await asyncio.sleep(10)
                try:
                    await self.heartbeat()
                except Exception as e:
                    logger.warning("Heartbeat failed: %s", e)

        self._heartbeat_task = asyncio.create_task(
            _loop(), name="conductor-heartbeat"
        )
        return self._heartbeat_task

    # --- Sandbox Ownership ---

    async def register_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"conductor:sandbox_owner:{sandbox_id}"
        await self._redis.set(key, self.instance_id, ex=300)

    async def claim_sandbox_owner(self, sandbox_id: uuid.UUID) -> bool:
        key = f"conductor:sandbox_owner:{sandbox_id}"
        result = await self._redis.set(key, self.instance_id, nx=True, ex=300)
        return result is not None

    async def refresh_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"conductor:sandbox_owner:{sandbox_id}"
        await self._redis.eval(
            REFRESH_IF_OWNER_LUA, 1, key, self.instance_id, "300"
        )

    async def remove_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"conductor:sandbox_owner:{sandbox_id}"
        await self._redis.eval(
            RELEASE_IF_OWNER_LUA, 1, key, self.instance_id
        )

    async def get_sandbox_owner(
        self, sandbox_id: uuid.UUID
    ) -> Optional[str]:
        key = f"conductor:sandbox_owner:{sandbox_id}"
        return await self._redis.get(key)

    async def list_active_sandbox_owners(self) -> list[uuid.UUID]:
        results = []
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match="conductor:sandbox_owner:*", count=100
            )
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode()
                uid_str = key_str.rsplit(":", 1)[-1]
                try:
                    results.append(uuid.UUID(uid_str))
                except ValueError:
                    pass
            if cursor == 0:
                break
        return results

    # --- Task-Sandbox Mapping ---

    async def set_task_sandbox(
        self, task_id: uuid.UUID, sandbox_id: uuid.UUID
    ) -> None:
        key = f"conductor:task_sandbox:{task_id}"
        await self._redis.set(key, str(sandbox_id), ex=7200)

    async def get_task_sandbox(
        self, task_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        key = f"conductor:task_sandbox:{task_id}"
        val = await self._redis.get(key)
        if val:
            try:
                return uuid.UUID(val if isinstance(val, str) else val.decode())
            except ValueError:
                pass
        return None

    async def remove_task_sandbox(self, task_id: uuid.UUID) -> None:
        key = f"conductor:task_sandbox:{task_id}"
        await self._redis.delete(key)

    # --- Distributed Locks ---

    async def try_acquire_lock(self, key: str, ttl_sec: int) -> bool:
        result = await self._redis.set(
            key, self.instance_id, nx=True, ex=ttl_sec
        )
        return result is not None

    async def release_lock(self, key: str) -> None:
        await self._redis.eval(
            RELEASE_IF_OWNER_LUA, 1, key, self.instance_id
        )

    # --- Pub/Sub Events ---

    async def publish_event(self, task_id: uuid.UUID, payload: str) -> None:
        channel = f"conductor:events:{task_id}"
        try:
            await self._redis.publish(channel, payload)
        except Exception as e:
            logger.warning("Failed to publish task event: %s", e)

    async def publish_session_event(
        self, session_id: uuid.UUID, payload: str
    ) -> None:
        channel = f"conductor:session_events:{session_id}"
        try:
            await self._redis.publish(channel, payload)
        except Exception as e:
            logger.warning("Failed to publish session event: %s", e)

    async def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None:
        key = f"conductor:queue:sandbox:{sandbox_id}"
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning("Failed to remove sandbox queue: %s", e)

    # --- Cross-Instance Commands ---

    async def send_instance_command(
        self, target_instance_id: str, command: dict
    ) -> None:
        channel = f"conductor:cmd:{target_instance_id}"
        await self._redis.publish(channel, json.dumps(command))

    def command_channel(self) -> str:
        return f"conductor:cmd:{self.instance_id}"

    # --- Cleanup ---

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        key = f"conductor:instances:{self.instance_id}"
        try:
            await self._redis.delete(key)
        except Exception:
            pass
