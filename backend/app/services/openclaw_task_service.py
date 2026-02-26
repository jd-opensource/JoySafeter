"""
OpenClaw Task service – submit, stream, cancel.

Tasks are dispatched to the least-loaded worker via the WorkerService,
then streamed back to clients through Redis Pub/Sub.
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
from app.services.openclaw_worker_service import OpenClawWorkerService

WORKER_REQUEST_TIMEOUT = 300  # max execution time per task (seconds)


def _channel_name(task_id: str) -> str:
    return f"openclaw:task:{task_id}"


class OpenClawTaskService(BaseService[OpenClawTask]):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.worker_service = OpenClawWorkerService(db)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        user_id: str,
        title: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> OpenClawTask:
        """Pick a worker, persist the task, then kick off async execution."""
        worker = await self.worker_service.get_available_worker()
        if not worker:
            raise RuntimeError("No available OpenClaw worker. Please try again later.")

        task_id = str(uuid.uuid4())
        channel = _channel_name(task_id)

        task = OpenClawTask(
            id=task_id,
            user_id=user_id,
            worker_id=worker.id,
            title=title,
            input_data=input_data or {},
            status="running",
            redis_channel=channel,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(task)
        await self.worker_service.increment_tasks(worker.id)
        await self.db.commit()
        await self.db.refresh(task)

        # Fire-and-forget the actual HTTP call to the worker
        asyncio.create_task(
            self._execute_on_worker(task_id, worker.id, worker.endpoint_url, input_data or {})
        )

        return task

    # ------------------------------------------------------------------
    # Execution (background coroutine)
    # ------------------------------------------------------------------

    async def _execute_on_worker(
        self,
        task_id: str,
        worker_id: str,
        endpoint_url: str,
        input_data: Dict[str, Any],
    ) -> None:
        """Call the worker's /run endpoint and stream output to Redis."""
        channel = _channel_name(task_id)
        try:
            async with httpx.AsyncClient(timeout=WORKER_REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{endpoint_url}/run",
                    json=input_data,
                ) as resp:
                    resp.raise_for_status()
                    collected: list[str] = []
                    async for chunk in resp.aiter_text():
                        if not chunk:
                            continue
                        collected.append(chunk)
                        await self._publish(channel, {"type": "output", "data": chunk})

            full_output = "".join(collected)
            await self._finish_task(task_id, worker_id, "completed", full_output)
            await self._publish(channel, {"type": "done"})

        except httpx.HTTPStatusError as exc:
            error_msg = f"Worker returned {exc.response.status_code}"
            logger.error(f"OpenClaw task {task_id} failed: {error_msg}")
            await self._finish_task(task_id, worker_id, "failed", error_msg)
            await self._publish(channel, {"type": "error", "message": error_msg})

        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"OpenClaw task {task_id} error: {error_msg}")
            await self._finish_task(task_id, worker_id, "failed", error_msg)
            await self._publish(channel, {"type": "error", "message": error_msg})

    async def _finish_task(
        self,
        task_id: str,
        worker_id: str,
        status: str,
        output: str,
    ) -> None:
        """Persist final state and release the worker slot.

        Uses a fresh DB session from the engine to avoid conflicts with the
        request-scoped session that may already be closed.
        """
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

            ws = OpenClawWorkerService(db)
            await ws.decrement_tasks(worker_id)

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel_task(self, task_id: str, user_id: str) -> Optional[OpenClawTask]:
        task = await self.get_task(task_id)
        if not task:
            return None
        if task.user_id != user_id:
            raise PermissionError("Cannot cancel another user's task")
        if task.status not in ("pending", "running"):
            return task  # already terminal

        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        if task.worker_id:
            await self.worker_service.decrement_tasks(task.worker_id)
        await self.db.commit()
        await self.db.refresh(task)

        await self._publish(_channel_name(task_id), {"type": "cancelled"})
        return task

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _publish(channel: str, payload: dict) -> None:
        client = RedisClient.get_client()
        if client:
            try:
                await client.publish(channel, json.dumps(payload, ensure_ascii=False))
            except Exception as exc:
                logger.warning(f"Failed to publish to {channel}: {exc}")
