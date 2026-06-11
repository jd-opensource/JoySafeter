"""Cross-instance HA coordination via Redis.

Ported from agentd/crates/joysafeter-store/src/redis_coord.rs.
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
    return redis.call("expire", KEYS[1], 300)
else
    return 0
end
"""


class RedisCoordinator:
    def __init__(self, redis_client, instance_id: str, config=None):
        self._redis = redis_client
        self.instance_id = instance_id
        self._config = config
        self._heartbeat_task: Optional[asyncio.Task] = None

    # --- Instance Registry ---

    async def register_instance(
        self, grpc_addr: str = "", http_addr: str = ""
    ) -> None:
        key = f"joysafeter:instances:{self.instance_id}"
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
        key = f"joysafeter:instances:{self.instance_id}"
        await self._redis.expire(key, 30)

    def spawn_heartbeat(self) -> asyncio.Task:
        interval = self._config.heartbeat_interval if self._config else 15
        ttl = self._config.heartbeat_ttl if self._config else 30

        async def _loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    key = f"joysafeter:instances:{self.instance_id}"
                    await self._redis.expire(key, ttl)
                except Exception as e:
                    logger.warning("Heartbeat failed: %s", e)

        self._heartbeat_task = asyncio.create_task(
            _loop(), name="joysafeter-heartbeat"
        )
        return self._heartbeat_task

    # --- Sandbox Ownership ---

    async def register_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"joysafeter:sandbox_owner:{sandbox_id}"
        await self._redis.set(key, self.instance_id, ex=300)

    async def claim_sandbox_owner(self, sandbox_id: uuid.UUID) -> bool:
        key = f"joysafeter:sandbox_owner:{sandbox_id}"
        result = await self._redis.set(key, self.instance_id, nx=True, ex=300)
        return result is not None

    async def refresh_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"joysafeter:sandbox_owner:{sandbox_id}"
        await self._redis.eval(
            REFRESH_IF_OWNER_LUA, 1, key, self.instance_id
        )

    async def remove_sandbox_owner(self, sandbox_id: uuid.UUID) -> None:
        key = f"joysafeter:sandbox_owner:{sandbox_id}"
        await self._redis.eval(
            RELEASE_IF_OWNER_LUA, 1, key, self.instance_id
        )

    async def get_sandbox_owner(
        self, sandbox_id: uuid.UUID
    ) -> Optional[str]:
        key = f"joysafeter:sandbox_owner:{sandbox_id}"
        return await self._redis.get(key)

    async def list_active_sandbox_owners(self) -> list[tuple[uuid.UUID, str]]:
        """Return (sandbox_id, owner_instance_id) pairs — matches Rust."""
        results: list[tuple[uuid.UUID, str]] = []
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match="joysafeter:sandbox_owner:*", count=100
            )
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode()
                uid_str = key_str.rsplit(":", 1)[-1]
                owner = await self._redis.get(key)
                if owner:
                    owner_str = owner if isinstance(owner, str) else owner.decode()
                    try:
                        results.append((uuid.UUID(uid_str), owner_str))
                    except ValueError:
                        pass
            if cursor == 0:
                break
        return results

    # --- Task-Sandbox Mapping ---

    async def set_task_sandbox(
        self, task_id: uuid.UUID, sandbox_id: uuid.UUID
    ) -> None:
        key = f"joysafeter:task_sandbox:{task_id}"
        await self._redis.set(key, str(sandbox_id), ex=7200)

    async def get_task_sandbox(
        self, task_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        key = f"joysafeter:task_sandbox:{task_id}"
        val = await self._redis.get(key)
        if val:
            try:
                return uuid.UUID(val if isinstance(val, str) else val.decode())
            except ValueError:
                pass
        return None

    async def remove_task_sandbox(self, task_id: uuid.UUID) -> None:
        key = f"joysafeter:task_sandbox:{task_id}"
        await self._redis.delete(key)

    # --- Distributed Locks ---

    async def try_acquire_lock(self, lock_name: str, ttl_sec: int) -> bool:
        key = f"joysafeter:lock:{lock_name}"
        result = await self._redis.set(
            key, self.instance_id, nx=True, ex=ttl_sec
        )
        return result is not None

    async def release_lock(self, lock_name: str) -> bool:
        key = f"joysafeter:lock:{lock_name}"
        result = await self._redis.eval(
            RELEASE_IF_OWNER_LUA, 1, key, self.instance_id
        )
        return bool(result)

    # --- Pub/Sub Events ---

    async def publish_event(self, task_id: uuid.UUID, payload: str) -> None:
        channel = f"joysafeter:events:{task_id}"
        try:
            await self._redis.publish(channel, payload)
        except Exception as e:
            logger.warning("Failed to publish task event: %s", e)

    async def publish_session_event(
        self, session_id: uuid.UUID, payload: str
    ) -> None:
        """Publish session event wrapped with source_instance — matches Rust."""
        channel = f"joysafeter:session_events:{session_id}"
        try:
            wrapped = json.dumps({
                "source_instance": self.instance_id,
                "event": json.loads(payload),
            })
            await self._redis.publish(channel, wrapped)
        except Exception as e:
            logger.warning("Failed to publish session event: %s", e)

    async def is_healthy(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None:
        key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning("Failed to remove sandbox queue: %s", e)

    # --- Task Queues ---

    async def push_to_global_queue(self, task_id: uuid.UUID) -> None:
        await self._redis.rpush("joysafeter:global_queue", str(task_id))

    async def pop_from_global_queue(
        self, timeout_secs: float
    ) -> Optional[uuid.UUID]:
        result = await self._redis.blpop("joysafeter:global_queue", timeout=int(timeout_secs))
        if result:
            _, val = result
            val_str = val if isinstance(val, str) else val.decode()
            try:
                return uuid.UUID(val_str)
            except ValueError:
                return None
        return None

    async def push_to_sandbox_queue(
        self, sandbox_id: uuid.UUID, task_id: uuid.UUID
    ) -> None:
        key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
        channel = f"joysafeter:sandbox_wakeup_channel:{sandbox_id}"
        pipe = self._redis.pipeline()
        pipe.set(key, "1", ex=60)
        pipe.publish(channel, "1")
        await pipe.execute()

    async def pop_from_sandbox_queue(
        self, sandbox_id: uuid.UUID, timeout_secs: float
    ) -> Optional[uuid.UUID]:
        key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
        claimed = await self._redis.get(key)
        if claimed is not None:
            await self._redis.delete(key)
            return sandbox_id

        pubsub = self._redis.pubsub()
        channel = f"joysafeter:sandbox_wakeup_channel:{sandbox_id}"
        try:
            await pubsub.subscribe(channel)
            claimed = await self._redis.get(key)
            if claimed is not None:
                await self._redis.delete(key)
                return sandbox_id
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=max(timeout_secs, 0.1),
            )
            if message is not None:
                await self._redis.delete(key)
                return sandbox_id
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
                if close is not None:
                    close_result = close()
                    if asyncio.iscoroutine(close_result):
                        await close_result
            except Exception:
                pass
        return None

    async def drain_sandbox_queue(
        self, sandbox_id: uuid.UUID
    ) -> list[uuid.UUID]:
        key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
        await self._redis.delete(key)
        return []

    # --- Cross-Instance Commands ---

    async def dispatch_cancel(
        self, sandbox_id: str, reason: str = ""
    ) -> None:
        """Publish a cancel command to all other instances — matches Rust."""
        command = json.dumps({
            "type": "cancel",
            "sandbox_id": sandbox_id,
            "reason": reason,
        })
        instances = await self._list_instance_ids()
        for inst_id in instances:
            if inst_id == self.instance_id:
                continue
            channel = f"joysafeter:cmd:{inst_id}"
            try:
                await self._redis.publish(channel, command)
            except Exception as e:
                logger.warning("dispatch_cancel to %s failed: %s", inst_id, e)

    async def dispatch_input(
        self, sandbox_id: str, content: str
    ) -> None:
        """Publish an input command to all other instances — matches Rust."""
        command = json.dumps({
            "type": "input",
            "sandbox_id": sandbox_id,
            "content": content,
        })
        instances = await self._list_instance_ids()
        for inst_id in instances:
            if inst_id == self.instance_id:
                continue
            channel = f"joysafeter:cmd:{inst_id}"
            try:
                await self._redis.publish(channel, command)
            except Exception as e:
                logger.warning("dispatch_input to %s failed: %s", inst_id, e)

    async def _list_instance_ids(self) -> list[str]:
        """List all active instance IDs from the registry."""
        ids: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match="joysafeter:instances:*", count=100
            )
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode()
                ids.append(key_str.rsplit(":", 1)[-1])
            if cursor == 0:
                break
        return ids

    async def send_instance_command(
        self, target_instance_id: str, command: dict
    ) -> None:
        channel = f"joysafeter:cmd:{target_instance_id}"
        await self._redis.publish(channel, json.dumps(command))

    def command_channel(self) -> str:
        return f"joysafeter:cmd:{self.instance_id}"

    # --- Cleanup ---

    async def deregister_instance(self) -> None:
        """Explicitly remove this instance from the registry — matches Rust."""
        key = f"joysafeter:instances:{self.instance_id}"
        try:
            await self._redis.delete(key)
            logger.info("Deregistered instance %s", self.instance_id)
        except Exception as e:
            logger.warning("Failed to deregister instance: %s", e)

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await self.deregister_instance()
