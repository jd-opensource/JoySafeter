"""
OpenClaw Task service — submit, stream, cancel.

Tasks are dispatched to the user's dedicated OpenClaw instance via the
OpenAI-compatible /v1/chat/completions API with SSE streaming.
Output is relayed to Redis Pub/Sub for real-time WebSocket delivery.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import RedisClient
from app.models.openclaw_task import OpenClawTask
from app.services.base import BaseService
from app.services.openclaw_instance_service import OpenClawInstanceService

INSTANCE_REQUEST_TIMEOUT = 300


def _channel_name(task_id: str) -> str:
    return f"openclaw:task:{task_id}"


class OpenClawTaskService(BaseService[OpenClawTask]):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.instance_service = OpenClawInstanceService(db)

    async def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[OpenClawTask]:
        stmt = select(OpenClawTask).order_by(OpenClawTask.created_at.desc())
        if user_id:
            stmt = stmt.where(OpenClawTask.user_id == user_id)
        if status:
            stmt = stmt.where(OpenClawTask.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_task(self, task_id: str) -> Optional[OpenClawTask]:
        result = await self.db.execute(
            select(OpenClawTask).where(OpenClawTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def submit_task(
        self,
        user_id: str,
        title: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> OpenClawTask:
        """Ensure user instance is running, persist task, then fire async execution."""
        instance = await self.instance_service.ensure_instance_running(user_id)

        task_id = str(uuid.uuid4())
        channel = _channel_name(task_id)

        task = OpenClawTask(
            id=task_id,
            user_id=user_id,
            instance_id=instance.id,
            title=title,
            input_data=input_data or {},
            status="running",
            redis_channel=channel,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)

        asyncio.create_task(
            self._execute_on_instance(
                task_id=task_id,
                instance_id=instance.id,
                gateway_port=instance.gateway_port,
                gateway_token=instance.gateway_token,
                input_data=input_data or {},
            )
        )

        return task

    async def _execute_on_instance(
        self,
        task_id: str,
        instance_id: str,
        gateway_port: int,
        gateway_token: str,
        input_data: Dict[str, Any],
    ) -> None:
        """Call the OpenClaw /api/run endpoint with SSE streaming."""
        channel = _channel_name(task_id)
        # TODO: Need to confirm what the actual OpenClaw Gateway API endpoint is
        url = f"http://127.0.0.1:{gateway_port}/api/run"


    async def _finish_task(
        self,
        task_id: str,
        status: str,
        output: str,
    ) -> None:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            task = (
                await db.execute(
                    select(OpenClawTask).where(OpenClawTask.id == task_id)
                )
            ).scalar_one_or_none()
            if task:
                task.status = status
                task.output = output
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def cancel_task(self, task_id: str, user_id: str) -> Optional[OpenClawTask]:
        task = await self.get_task(task_id)
        if not task:
            return None
        if task.user_id != user_id:
            raise PermissionError("Cannot cancel another user's task")
        if task.status not in ("pending", "running"):
            return task

        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(task)

        await self._publish(_channel_name(task_id), {"type": "cancelled"})
        return task

    async def delete_task(self, task_id: str, user_id: str) -> bool:
        task = await self.get_task(task_id)
        if not task:
            return False
        if task.user_id != user_id:
            raise PermissionError("Cannot delete another user's task")

        await self.db.delete(task)
        await self.db.commit()
        return True

    @staticmethod
    async def _publish(channel: str, payload: dict) -> None:
        client = RedisClient.get_client()
        if client:
            try:
                await client.publish(channel, json.dumps(payload, ensure_ascii=False))
            except Exception as exc:
                logger.warning(f"Failed to publish to {channel}: {exc}")
