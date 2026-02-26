"""Redis-backed event bus for Security Dept task streams."""

from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from app.core.redis import RedisClient
from app.core.settings import settings


class SecurityDeptEventBus:
    """Publishes task events through Redis Pub/Sub with graceful fallback."""

    @staticmethod
    def channel(task_id: str) -> str:
        return f"security_dept:task:{task_id}:events"

    @staticmethod
    def status_key(task_id: str) -> str:
        return f"security_dept:task:{task_id}:status"

    @staticmethod
    def build_event(task_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "task_id": task_id,
            "timestamp": int(time.time() * 1000),
            "data": data,
        }

    @classmethod
    async def publish(cls, task_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        event = cls.build_event(task_id, event_type, data)

        if not RedisClient.is_available() or RedisClient.get_client() is None:
            logger.debug(f"SecurityDept event bus skipped (redis unavailable): task={task_id} type={event_type}")
            return event

        try:
            redis_client = RedisClient.get_client()
            assert redis_client is not None
            payload = json.dumps(event, ensure_ascii=False)
            ttl = settings.security_dept_event_ttl_seconds

            await redis_client.publish(cls.channel(task_id), payload)
            await RedisClient.set(cls.status_key(task_id), event_type, expire=ttl)
        except Exception as exc:
            logger.warning(f"Failed to publish SecurityDept event: task={task_id} type={event_type} error={exc}")

        return event
