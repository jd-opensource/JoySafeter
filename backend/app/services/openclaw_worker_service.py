"""
OpenClaw Worker lifecycle management service.

Handles worker registration, health checking, load balancing,
and optional Docker-based dynamic provisioning.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.openclaw_worker import OpenClawWorker
from app.services.base import BaseService

HEALTH_TIMEOUT_SECONDS = 5


class OpenClawWorkerService(BaseService[OpenClawWorker]):
    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    async def list_workers(self) -> List[OpenClawWorker]:
        result = await self.db.execute(
            select(OpenClawWorker).order_by(OpenClawWorker.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_worker(self, worker_id: str) -> Optional[OpenClawWorker]:
        result = await self.db.execute(
            select(OpenClawWorker).where(OpenClawWorker.id == worker_id)
        )
        return result.scalar_one_or_none()

    async def get_worker_by_endpoint(self, endpoint_url: str) -> Optional[OpenClawWorker]:
        result = await self.db.execute(
            select(OpenClawWorker).where(OpenClawWorker.endpoint_url == endpoint_url)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_worker(
        self,
        name: str,
        endpoint_url: str,
        max_tasks: int = 3,
        container_id: Optional[str] = None,
    ) -> OpenClawWorker:
        """Register a new worker or re-activate an existing one."""
        existing = await self.get_worker_by_endpoint(endpoint_url)
        if existing:
            existing.name = name
            existing.status = "idle"
            existing.max_tasks = max_tasks
            existing.container_id = container_id
            existing.error_message = None
            existing.last_heartbeat_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(existing)
            logger.info(f"Re-registered OpenClaw worker: {existing.id} ({endpoint_url})")
            return existing

        worker = OpenClawWorker(
            id=str(uuid.uuid4()),
            name=name,
            endpoint_url=endpoint_url.rstrip("/"),
            status="idle",
            container_id=container_id,
            current_tasks=0,
            max_tasks=max_tasks,
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        self.db.add(worker)
        await self.db.commit()
        await self.db.refresh(worker)
        logger.info(f"Registered new OpenClaw worker: {worker.id} ({endpoint_url})")
        return worker

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    async def remove_worker(self, worker_id: str) -> bool:
        worker = await self.get_worker(worker_id)
        if not worker:
            return False
        await self.db.delete(worker)
        await self.db.commit()
        logger.info(f"Removed OpenClaw worker: {worker_id}")
        return True

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def ping_worker(self, worker: OpenClawWorker) -> bool:
        """Ping a single worker, update status accordingly."""
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
                resp = await client.get(f"{worker.endpoint_url}/health")
                alive = resp.status_code == 200
        except Exception:
            alive = False

        now = datetime.now(timezone.utc)
        if alive:
            worker.status = "idle" if worker.current_tasks == 0 else "busy"
            worker.last_heartbeat_at = now
            worker.error_message = None
        else:
            worker.status = "offline"
            worker.error_message = "Health check failed"

        await self.db.commit()
        await self.db.refresh(worker)
        return alive

    async def health_check_all(self) -> dict:
        """Ping every registered worker and return summary."""
        workers = await self.list_workers()
        results = {"total": len(workers), "online": 0, "offline": 0}
        for w in workers:
            ok = await self.ping_worker(w)
            if ok:
                results["online"] += 1
            else:
                results["offline"] += 1
        return results

    # ------------------------------------------------------------------
    # Load balancing — Least Connections
    # ------------------------------------------------------------------

    async def get_available_worker(self) -> Optional[OpenClawWorker]:
        """Return the worker with the fewest running tasks that still has capacity."""
        result = await self.db.execute(
            select(OpenClawWorker)
            .where(OpenClawWorker.status.in_(["idle", "busy"]))
            .where(OpenClawWorker.current_tasks < OpenClawWorker.max_tasks)
            .order_by(OpenClawWorker.current_tasks.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Task counter helpers (called by TaskService)
    # ------------------------------------------------------------------

    async def increment_tasks(self, worker_id: str) -> None:
        await self.db.execute(
            update(OpenClawWorker)
            .where(OpenClawWorker.id == worker_id)
            .values(
                current_tasks=OpenClawWorker.current_tasks + 1,
                status="busy",
            )
        )
        await self.db.commit()

    async def decrement_tasks(self, worker_id: str) -> None:
        await self.db.execute(
            update(OpenClawWorker)
            .where(OpenClawWorker.id == worker_id)
            .values(current_tasks=OpenClawWorker.current_tasks - 1)
        )
        await self.db.commit()
        # Flip status back to idle if no tasks remain
        worker = await self.get_worker(worker_id)
        if worker and worker.current_tasks <= 0:
            worker.current_tasks = 0
            worker.status = "idle"
            await self.db.commit()
