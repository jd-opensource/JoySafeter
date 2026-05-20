import asyncio
import logging
import uuid
from datetime import timedelta

from app.conductor.kernel.retry import compute_retry_delay

logger = logging.getLogger(__name__)


class TaskController:
    def __init__(self, queue):
        self._queue = queue

    async def run(self) -> None:
        logger.info("TaskController watchdog started (60s interval)")
        while True:
            await asyncio.sleep(60)
            try:
                await self._check_overdue_tasks()
            except Exception as e:
                logger.warning("Overdue task check failed: %s", e)
            try:
                await self._check_stuck_scheduling()
            except Exception as e:
                logger.warning("Stuck scheduling check failed: %s", e)

    async def recover_on_startup(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import TaskStatus, ConductorTask
        from app.conductor.models.sandbox import ConductorSandbox
        from sqlalchemy import update, and_, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_recovery'))"))
            locked = result.scalar()
            if not locked:
                logger.info("Recovery lock held by another instance, skipping")
                return

            try:
                await db.execute(
                    update(ConductorTask)
                    .where(
                        and_(
                            ConductorTask.status == "running",
                            ConductorTask.started_at.isnot(None),
                            text("started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"),
                        )
                    )
                    .values(status="failed", error="Orchestrator restarted", completed_at=text("NOW()"))
                )

                await db.execute(
                    update(ConductorTask)
                    .where(ConductorTask.status == "scheduling")
                    .values(status="pending")
                )

                await db.execute(
                    update(ConductorSandbox)
                    .where(
                        and_(
                            ConductorSandbox.status == "provisioning",
                            text("created_at < NOW() - INTERVAL '20 minutes'"),
                        )
                    )
                    .values(status="stopped")
                )

                # Reset orphaned running/idle sandboxes that have no active bridge
                # (orchestrator crashed while they were active)
                from app.conductor.lifespan import get_redis_coordinator
                coordinator = get_redis_coordinator()
                orphan_threshold = "30 minutes" if coordinator else "10 minutes"

                owned_sandbox_ids: list[uuid.UUID] = []
                if coordinator:
                    try:
                        owned_sandbox_ids = await coordinator.list_active_sandbox_owners()
                    except Exception as e:
                        logger.warning("Failed to list sandbox owners during recovery: %s", e)

                orphan_query = (
                    update(ConductorSandbox)
                    .where(
                        and_(
                            ConductorSandbox.status.in_(["running", "idle"]),
                            text(f"last_used_at < NOW() - INTERVAL '{orphan_threshold}'"),
                        )
                    )
                    .values(status="idle")
                )
                if owned_sandbox_ids:
                    orphan_query = orphan_query.where(
                        ConductorSandbox.id.notin_(owned_sandbox_ids)
                    )
                await db.execute(orphan_query)

                await db.commit()
                logger.info("Startup recovery complete")
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_recovery'))"))

    async def _check_overdue_tasks(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import ConductorTask
        from sqlalchemy import update, and_, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_watchdog'))"))
            locked = result.scalar()
            if not locked:
                return

            try:
                await db.execute(
                    update(ConductorTask)
                    .where(
                        and_(
                            ConductorTask.status == "running",
                            ConductorTask.started_at.isnot(None),
                            text("started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"),
                        )
                    )
                    .values(status="timeout", error="Task timed out", completed_at=text("NOW()"))
                )
                await db.commit()
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_watchdog'))"))

    async def _check_stuck_scheduling(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import ConductorTask
        from sqlalchemy import update, and_, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(ConductorTask)
                .where(
                    and_(
                        ConductorTask.status == "scheduling",
                        text("updated_at < NOW() - INTERVAL '2 minutes'"),
                    )
                )
                .values(status="pending")
                .returning(ConductorTask.id)
            )
            rows = result.all()
            if rows:
                for (tid,) in rows:
                    logger.warning("Task %s stuck in scheduling >2min, reset to pending", tid)
                    await self._queue.push_global(tid)
            await db.commit()

    @staticmethod
    async def failover_or_fail_task(task_id: uuid.UUID, reason: str) -> bool:
        from app.core.database import AsyncSessionLocal
        from app.conductor.services.task_service import TaskService
        from app.conductor.models.task import TaskStatus

        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if not task:
                return False

            status = TaskStatus(task.status)
            if status.is_terminal():
                return False

            if task.retry_count < task.max_retries:
                await svc.increment_retry(task_id)
                return True

            await svc.update_task_status(task_id, TaskStatus.FAILED, error=reason)
            return False
