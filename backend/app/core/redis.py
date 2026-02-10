"""
Redis Configuration - Cache and Distributed Lock
"""

import json
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Dict, Optional, cast

import redis.asyncio as redis_async
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import LockError

from .settings import settings


class RedisClient:
    """Redis Client Wrapper"""

    _pool: Optional[ConnectionPool] = None
    _client: Optional[redis_async.Redis] = None
    _is_available: bool = False

    @classmethod
    async def init(cls):
        """Initialize connection pool"""
        if settings.redis_url and not cls._pool:
            try:
                cls._pool = ConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=settings.redis_pool_size,
                    decode_responses=True,
                )
                cls._client = redis_async.Redis(connection_pool=cls._pool)

                # Health check
                await cls._client.ping()
                cls._is_available = True
                print(f"   ✅ Redis connected: {settings.redis_url}")
            except Exception as e:
                cls._is_available = False
                print(f"   ⚠️  Redis connection failed: {e}")
                print("   ⚠️  Refresh token and rate limiting features will be degraded")
                # Do not raise exception, allow app to start (degraded mode)

    @classmethod
    async def close(cls):
        """Close connection"""
        if cls._client:
            await cls._client.close()
            cls._client = None
        if cls._pool:
            await cls._pool.disconnect()
            cls._pool = None
        cls._is_available = False

    @classmethod
    def get_client(cls) -> Optional[redis_async.Redis]:
        """Get Redis client"""
        return cls._client

    @classmethod
    def is_available(cls) -> bool:
        """Check if Redis is available"""
        return cls._is_available

    @classmethod
    async def health_check(cls) -> bool:
        """Health check"""
        if not cls._client:
            return False
        try:
            # Type assertion: ping() in async context always returns Awaitable[bool]
            ping_result: Awaitable[bool] = cast(Awaitable[bool], cls._client.ping())
            await ping_result
            cls._is_available = True
            return True
        except Exception:
            cls._is_available = False
            return False

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """Get value"""
        if not cls._client:
            return None
        result = await cls._client.get(key)
        return str(result) if result is not None else None

    @classmethod
    async def set(
        cls,
        key: str,
        value: Any,
        expire: int = 3600,
    ) -> bool:
        """Set value"""
        if not cls._client:
            return False

        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)

        await cls._client.set(key, value, ex=expire)
        return True

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete key"""
        if not cls._client:
            return False
        await cls._client.delete(key)
        return True

    @classmethod
    async def exists(cls, key: str) -> bool:
        """Check if key exists"""
        if not cls._client:
            return False
        result = await cls._client.exists(key)
        # exists returns int (number of keys existing)
        return bool(result > 0) if result is not None else False

    @classmethod
    async def incr(cls, key: str, amount: int = 1) -> int:
        """Increment counter"""
        if not cls._client:
            return 0
        result = await cls._client.incrby(key, amount)
        return int(result) if result is not None else 0

    @classmethod
    async def expire(cls, key: str, seconds: int) -> bool:
        """Set expiration time"""
        if not cls._client:
            return False
        result = await cls._client.expire(key, seconds)
        return bool(result) if result is not None else False

    @classmethod
    @asynccontextmanager
    async def lock(cls, name: str, timeout: int = 60, blocking_timeout: int = 60):
        """Distributed Lock
        Args:
            name: Lock name
            timeout: Lock auto-release time (to avoid deadlocks), default 60s
            blocking_timeout: Max time to wait for lock acquisition, default 60s
        """
        if not cls._client:
            yield True
            return

        # Use redis-py lock
        lock = cls._client.lock(name, timeout=timeout, blocking_timeout=blocking_timeout)
        acquired = False
        try:
            # Try to acquire lock
            # blocking=True is default, but explicit is better for async implementation
            acquired = await lock.acquire(blocking=True)
            if not acquired:
                raise TimeoutError(f"Could not acquire lock {name} within {blocking_timeout} seconds")
            yield True

        except TimeoutError:
            raise
        finally:
            if acquired:
                try:
                    await lock.release()
                except LockError:
                    # Lock might have expired (execution time > timeout) or ownership lost
                    pass
                except Exception as e:
                    print(f"   ⚠️  Error releasing lock {name}: {e}")

    # ==================== Copilot Session Methods ====================

    @classmethod
    async def append_copilot_content(cls, session_id: str, content: str, ttl: int = 86400) -> bool:
        """Append Copilot session real-time content"""
        if not cls._client:
            return False
        key = f"copilot:session:{session_id}:content"
        await cls._client.append(key, content)
        await cls._client.expire(key, ttl)
        return True

    @classmethod
    async def publish_copilot_event(cls, session_id: str, event: Dict[str, Any]) -> bool:
        """Publish Copilot event to Pub/Sub"""
        if not cls._client:
            return False
        channel = f"copilot:session:{session_id}:pubsub"
        event_str = json.dumps(event, ensure_ascii=False)
        await cls._client.publish(channel, event_str)
        return True

    @classmethod
    async def set_copilot_status(cls, session_id: str, status: str, ttl: int = 86400) -> bool:
        """Set Copilot session status"""
        if not cls._client:
            return False
        key = f"copilot:session:{session_id}:status"
        await cls._client.set(key, status, ex=ttl)
        return True

    @classmethod
    async def get_copilot_status(cls, session_id: str) -> Optional[str]:
        """Get Copilot session status"""
        if not cls._client:
            return None
        key = f"copilot:session:{session_id}:status"
        result = await cls._client.get(key)
        return str(result) if result is not None else None

    @classmethod
    async def get_copilot_content(cls, session_id: str) -> Optional[str]:
        """Get Copilot session accumulated content"""
        if not cls._client:
            return None
        key = f"copilot:session:{session_id}:content"
        result = await cls._client.get(key)
        return str(result) if result is not None else None

    @classmethod
    async def get_copilot_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        """Get Copilot session data (status and content)"""
        if not cls._client:
            return None
        status = await cls.get_copilot_status(session_id)
        if status is None:
            return None
        content = await cls.get_copilot_content(session_id) or ""
        return {
            "session_id": session_id,
            "status": status,
            "content": content,
        }

    @classmethod
    async def cleanup_copilot_session(cls, session_id: str) -> bool:
        """Clean up Copilot session temporary data"""
        if not cls._client:
            return False
        keys = [
            f"copilot:session:{session_id}:status",
            f"copilot:session:{session_id}:content",
        ]
        if keys:
            await cls._client.delete(*keys)
        return True


# Helper function
async def get_redis() -> Optional[redis_async.Redis]:
    """Get Redis client"""
    return RedisClient.get_client()
