"""
Redis 配置 - 缓存和分布式锁
"""

import json
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Dict, Optional, cast

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from .settings import settings


class RedisClient:
    """Redis 客户端封装"""

    _pool: Optional[ConnectionPool] = None
    _client: Optional[redis.Redis] = None
    _is_available: bool = False

    @classmethod
    async def init(cls):
        """初始化连接池"""
        if settings.redis_url and not cls._pool:
            try:
                cls._pool = ConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=settings.redis_pool_size,
                    decode_responses=True,
                )
                cls._client = redis.Redis(connection_pool=cls._pool)

                # 健康检查
                await cls._client.ping()
                cls._is_available = True
                print(f"   ✅ Redis connected: {settings.redis_url}")
            except Exception as e:
                cls._is_available = False
                print(f"   ⚠️  Redis connection failed: {e}")
                print("   ⚠️  Refresh token and rate limiting features will be degraded")
                # 不抛出异常，允许应用启动（降级模式）

    @classmethod
    async def close(cls):
        """关闭连接"""
        if cls._client:
            await cls._client.close()
            cls._client = None
        if cls._pool:
            await cls._pool.disconnect()
            cls._pool = None
        cls._is_available = False

    @classmethod
    def get_client(cls) -> Optional[redis.Redis]:
        """获取 Redis 客户端"""
        return cls._client

    @classmethod
    def is_available(cls) -> bool:
        """检查 Redis 是否可用"""
        return cls._is_available

    @classmethod
    async def health_check(cls) -> bool:
        """健康检查"""
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
        """获取值"""
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
        """设置值"""
        if not cls._client:
            return False

        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)

        await cls._client.set(key, value, ex=expire)
        return True

    @classmethod
    async def delete(cls, key: str) -> bool:
        """删除键"""
        if not cls._client:
            return False
        await cls._client.delete(key)
        return True

    @classmethod
    async def exists(cls, key: str) -> bool:
        """检查键是否存在"""
        if not cls._client:
            return False
        result = await cls._client.exists(key)
        return bool(result > 0) if result is not None else False

    @classmethod
    async def incr(cls, key: str, amount: int = 1) -> int:
        """增加计数"""
        if not cls._client:
            return 0
        result = await cls._client.incrby(key, amount)
        return int(result) if result is not None else 0

    @classmethod
    async def expire(cls, key: str, seconds: int) -> bool:
        """设置过期时间"""
        if not cls._client:
            return False
        result = await cls._client.expire(key, seconds)
        return bool(result) if result is not None else False

    @classmethod
    @asynccontextmanager
    async def lock(cls, name: str, timeout: int = 10):
        """分布式锁"""
        if not cls._client:
            yield True
            return

        lock = cls._client.lock(name, timeout=timeout)
        try:
            await lock.acquire()
            yield True
        finally:
            await lock.release()

    # ==================== Copilot Session Methods ====================

    @classmethod
    async def append_copilot_content(cls, session_id: str, content: str, ttl: int = 86400) -> bool:
        """追加 Copilot 会话的实时内容"""
        if not cls._client:
            return False
        key = f"copilot:session:{session_id}:content"
        await cls._client.append(key, content)
        await cls._client.expire(key, ttl)
        return True

    @classmethod
    async def publish_copilot_event(cls, session_id: str, event: Dict[str, Any]) -> bool:
        """发布 Copilot 事件到 Pub/Sub"""
        if not cls._client:
            return False
        channel = f"copilot:session:{session_id}:pubsub"
        event_str = json.dumps(event, ensure_ascii=False)
        await cls._client.publish(channel, event_str)
        return True

    @classmethod
    async def set_copilot_status(cls, session_id: str, status: str, ttl: int = 86400) -> bool:
        """设置 Copilot 会话状态"""
        if not cls._client:
            return False
        key = f"copilot:session:{session_id}:status"
        await cls._client.set(key, status, ex=ttl)
        return True

    @classmethod
    async def get_copilot_status(cls, session_id: str) -> Optional[str]:
        """获取 Copilot 会话状态"""
        if not cls._client:
            return None
        key = f"copilot:session:{session_id}:status"
        result = await cls._client.get(key)
        return str(result) if result is not None else None

    @classmethod
    async def get_copilot_content(cls, session_id: str) -> Optional[str]:
        """获取 Copilot 会话的累积内容"""
        if not cls._client:
            return None
        key = f"copilot:session:{session_id}:content"
        result = await cls._client.get(key)
        return str(result) if result is not None else None

    @classmethod
    async def get_copilot_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 Copilot 会话数据（状态和内容）"""
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
        """清理 Copilot 会话的临时数据"""
        if not cls._client:
            return False
        keys = [
            f"copilot:session:{session_id}:status",
            f"copilot:session:{session_id}:content",
        ]
        if keys:
            await cls._client.delete(*keys)
        return True


# 便捷函数
async def get_redis() -> Optional[redis.Redis]:
    """获取 Redis 客户端"""
    return RedisClient.get_client()
