import asyncio
import logging
import uuid

from app.joysafeter_shared.retry import compute_retry_delay

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
            try:
                await self._scan_pending_tasks()
            except Exception as e:
                logger.warning("Pending task scanner failed: %s", e)

    async def run_lease_manager(self) -> None:
        """Fast loop that keeps this instance's running-task leases fresh and
        reclaims tasks whose owner instance has gone away.

        Runs far more often than the lease TTL so a live owner never lets its
        own lease lapse; the reclaim scan then only ever sees genuinely
        abandoned tasks and requeues them in seconds instead of waiting for the
        ~2h ``timeout_sec`` upper bound.
        """
        from app.joysafeter_shared.config.settings import joysafeter_config

        interval = max(1, joysafeter_config.task_lease_renew_interval_sec)
        logger.info("TaskController lease manager started (%ds interval)", interval)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._renew_own_leases()
            except Exception as e:
                logger.warning("Lease renewal failed: %s", e)
            try:
                await self._reclaim_expired_leases()
            except Exception as e:
                logger.warning("Lease reclaim scan failed: %s", e)

    async def _renew_own_leases(self) -> None:
        from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine
        from app.joysafeter_shared.config.settings import joysafeter_config
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            renewed = await JoySafeterTaskStateMachine(db).renew_leases(joysafeter_config.instance_id)
            if renewed:
                logger.debug("Renewed lease on %d running task(s)", renewed)

    async def _reclaim_expired_leases(self) -> None:
        from sqlalchemy import text

        from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            locked = False
            try:
                lock_result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_lease_reclaim'))"))
                locked = bool(lock_result.scalar())
                if not locked:
                    return

                expired = await JoySafeterTaskStateMachine(db).find_lease_expired_running()
                for task_id in expired:
                    logger.warning("Task %s lease expired — owner presumed dead, reclaiming", task_id)
                    retry_count = await self.failover_or_fail_task(
                        task_id, "Lease expired — owner instance presumed dead"
                    )
                    if retry_count is not None:
                        await self._queue.push_to_global(task_id)
                        logger.info("Reclaimed task %s re-enqueued (retry %d)", task_id, retry_count)
                if expired:
                    logger.info("Lease reclaim reclaimed %d abandoned running task(s)", len(expired))
            finally:
                if locked:
                    await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_lease_reclaim'))"))

    async def recover_on_startup(self) -> None:
        from sqlalchemy import text

        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import JoySafeterSessionLifecycleService, TaskService
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_recovery'))"))
            locked = result.scalar()
            if not locked:
                logger.info("Recovery lock held by another instance, skipping")
                return

            try:
                from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

                coordinator = get_redis_coordinator()
                redis_available = coordinator is not None
                task_svc = TaskService(db)
                sandbox_svc = SandboxService(db)

                # Running tasks that exceeded their timeout -> failed
                recovered_result = await db.execute(
                    text(
                        "SELECT id FROM joysafeter_tasks"
                        " WHERE status = 'running'"
                        " AND started_at IS NOT NULL"
                        " AND started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                    )
                )
                recovered_tasks = recovered_result.all()
                for row in recovered_tasks:
                    await task_svc.update_task_error(
                        row[0],
                        "Orchestrator restarted - task was running when process exited",
                        TaskStatus.FAILED,
                    )

                # DB pending tasks are the durable source of truth; enqueue all
                # of them on startup to compensate in-memory/Redis queue loss.
                pending_result = await db.execute(text("SELECT id FROM joysafeter_tasks WHERE status = 'pending'"))
                pending_tasks = pending_result.all()
                for row in pending_tasks:
                    await self._queue.push_to_global(row[0])

                # Scheduling tasks -> pending (unconditional, no time filter)
                stale_scheduling_result = await db.execute(
                    text("SELECT id FROM joysafeter_tasks WHERE status = 'scheduling'")
                )
                stale_scheduling = stale_scheduling_result.all()
                for row in stale_scheduling:
                    await task_svc.increment_retry(row[0])

                # Provisioning sandboxes: 45min with Redis, 20min without
                provisioning_minutes = 45 if redis_available else 20
                stale_provisioning_result = await db.execute(
                    text(
                        "SELECT id FROM joysafeter_sandboxes"
                        " WHERE status = 'provisioning'"
                        " AND created_at < NOW() - (:mins * INTERVAL '1 minute')"
                    ),
                    {"mins": provisioning_minutes},
                )
                stale_provisioning = stale_provisioning_result.all()
                for row in stale_provisioning:
                    await sandbox_svc.update_status(row[0], "stopped")

                session_lifecycle = JoySafeterSessionLifecycleService(db)

                # Reset sessions stuck in 'rescheduling'
                stale_rescheduling_result = await db.execute(
                    text(
                        "SELECT id FROM joysafeter_sessions"
                        " WHERE status = 'rescheduling'"
                        " AND updated_at < NOW() - INTERVAL '5 minutes'"
                    )
                )
                stale_rescheduling_sessions = stale_rescheduling_result.all()

                for row in stale_rescheduling_sessions:
                    sid = row[0]
                    await session_lifecycle.transition_and_emit(
                        sid,
                        SessionStatus.TERMINATED.value,
                        "session.status_terminated",
                        {"stop_reason": {"type": "retries_exhausted"}},
                        stop_reason={"type": "retries_exhausted"},
                    )

                # Reset sessions stuck in 'running' with no active tasks
                stale_running_result = await db.execute(
                    text(
                        "SELECT id FROM joysafeter_sessions"
                        " WHERE status = 'running'"
                        " AND updated_at < NOW() - INTERVAL '5 minutes'"
                        " AND NOT EXISTS ("
                        "     SELECT 1 FROM joysafeter_tasks"
                        "     WHERE joysafeter_tasks.chat_session_id = joysafeter_sessions.id"
                        "     AND joysafeter_tasks.status IN ('pending', 'scheduling', 'running')"
                        " )"
                    )
                )
                stale_running_sessions = stale_running_result.all()

                for row in stale_running_sessions:
                    sid = row[0]
                    await session_lifecycle.transition_and_emit(
                        sid,
                        SessionStatus.IDLE.value,
                        "session.status_idle",
                        {"stop_reason": {"type": "end_turn"}},
                        stop_reason={"type": "end_turn"},
                    )

                await db.commit()
                logger.info(
                    "Startup recovery complete: tasks_failed=%d pending_requeued=%d scheduling_reset=%d "
                    "provisioning_recovered=%d rescheduling_sessions_terminated=%d running_sessions_reset=%d "
                    "redis_available=%s",
                    len(recovered_tasks),
                    len(pending_tasks),
                    len(stale_scheduling),
                    len(stale_provisioning),
                    len(stale_rescheduling_sessions),
                    len(stale_running_sessions),
                    redis_available,
                )
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_recovery'))"))

    async def _check_overdue_tasks(self) -> None:
        from sqlalchemy import text

        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import JoySafeterSessionLifecycleService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            locked = False
            try:
                result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_watchdog'))"))
                locked = bool(result.scalar())
                if not locked:
                    return

                rows = (
                    await db.execute(
                        text(
                            "SELECT id, sandbox_id, chat_session_id FROM joysafeter_tasks"
                            " WHERE status = 'running'"
                            " AND started_at IS NOT NULL"
                            " AND started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                        )
                    )
                ).all()
                task_svc = TaskService(db)
                session_lifecycle = JoySafeterSessionLifecycleService(db)

                for row in rows:
                    task_id, sandbox_id, session_id = row[0], row[1], row[2]
                    logger.warning("Task %s exceeded timeout (sandbox=%s), marking timed out", task_id, sandbox_id)

                    await task_svc.update_task_error(
                        task_id,
                        "Task timed out (watchdog)",
                        TaskStatus.TIMEOUT,
                    )

                    if session_id is not None:
                        is_running = (
                            await db.execute(
                                text(
                                    "SELECT EXISTS(SELECT 1 FROM joysafeter_sessions WHERE id = :sid AND status = 'running')"
                                ),
                                {"sid": session_id},
                            )
                        ).scalar()

                        if is_running:
                            await session_lifecycle.transition_and_emit(
                                session_id,
                                SessionStatus.IDLE.value,
                                "session.status_idle",
                                {"stop_reason": {"type": "timeout"}},
                                stop_reason={"type": "timeout"},
                            )

                    logger.info("Timed-out task %s marked as timeout", task_id)

                await db.commit()
            finally:
                if locked:
                    await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_watchdog'))"))

    async def _check_stuck_scheduling(self) -> None:
        from sqlalchemy import text

        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            locked = False
            try:
                lock_result = await db.execute(
                    text("SELECT pg_try_advisory_lock(hashtext('task_scheduling_watchdog'))")
                )
                locked = bool(lock_result.scalar())
                if not locked:
                    return

                result = await db.execute(
                    text(
                        "SELECT id, retry_count, max_retries FROM joysafeter_tasks"
                        " WHERE status = 'scheduling'"
                        " AND updated_at < NOW() - INTERVAL '2 minutes'"
                    )
                )
                rows = result.all()
                task_svc = TaskService(db)
                requeue_ids = []
                for row in rows:
                    task_id = row[0]
                    retry_count = row[1] or 0
                    max_retries = row[2] or 3
                    if retry_count >= max_retries:
                        logger.warning(
                            "Task %s stuck in scheduling >2min and retries exhausted (%d/%d), marking failed",
                            task_id,
                            retry_count,
                            max_retries,
                        )
                        await task_svc.update_task_error(
                            task_id,
                            "Retries exhausted while stuck in scheduling",
                            TaskStatus.FAILED,
                        )
                    else:
                        await task_svc.increment_retry(task_id)
                        requeue_ids.append(task_id)
                        logger.warning("Task %s stuck in scheduling >2min, reset to pending and re-enqueued", task_id)

                for task_id in requeue_ids:
                    await self._queue.push_to_global(task_id)
            finally:
                if locked:
                    await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_scheduling_watchdog'))"))

    async def _scan_pending_tasks(self) -> None:
        from sqlalchemy import text

        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            locked = False
            try:
                lock_result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_pending_scanner'))"))
                locked = bool(lock_result.scalar())
                if not locked:
                    return

                rows = (
                    await db.execute(
                        text(
                            "SELECT id FROM joysafeter_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 500"
                        )
                    )
                ).all()
                for row in rows:
                    await self._queue.push_to_global(row[0])
                if rows:
                    logger.info("Pending task scanner re-enqueued %d task(s)", len(rows))
            finally:
                if locked:
                    await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_pending_scanner'))"))

    @staticmethod
    async def failover_or_fail_task(task_id: uuid.UUID, reason: str) -> "int | None":
        """Attempt to retry the task. Returns the retry_count (pre-increment) if retried, None if terminal/failed."""
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import JoySafeterSessionLifecycleService, SessionService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if not task:
                try:
                    await svc.update_task_error(task_id, reason, TaskStatus.FAILED)
                except Exception as e:
                    logger.error("Failed to mark task %s as failed: %s", task_id, e)
                return None

            status = TaskStatus(task.status)
            if status.is_terminal():
                logger.warning("Task %s already terminal (%s), skipping failover", task_id, status)
                return None

            # If the task already emitted agent.message events, it effectively completed
            # before the sandbox died — mark it completed instead of retrying
            if task.chat_session_id:
                session_svc = SessionService(db)
                has_output = await session_svc.task_has_agent_output(task_id, task.chat_session_id)
                if has_output:
                    logger.info(
                        "Task %s already produced output before sandbox death, marking completed",
                        task_id,
                    )
                    await svc.update_task_status(task_id, TaskStatus.COMPLETED)
                    # Transition session to idle since the task effectively finished.
                    try:
                        await JoySafeterSessionLifecycleService(db).transition_and_emit(
                            task.chat_session_id,
                            "idle",
                            "session.status_idle",
                            {"stop_reason": {"type": "end_turn"}},
                            stop_reason={"type": "end_turn"},
                        )
                    except Exception:
                        pass
                    return None

            if task.retry_count < task.max_retries:
                count = task.retry_count
                ok = await svc.increment_retry(task_id)
                if ok:
                    return count
                else:
                    logger.warning(
                        "CAS conflict on increment_task_retry for task %s — task may have been completed concurrently",
                        task_id,
                    )
                    return None

            try:
                await svc.update_task_error(task_id, reason, TaskStatus.FAILED)
            except Exception as e:
                logger.error("Failed to mark task %s as failed: %s", task_id, e)
            return None

    @staticmethod
    def compute_retry_delay(retry_count: int, task_id: uuid.UUID) -> float:
        """Compute retry delay in seconds, matching Rust TaskController::compute_retry_delay."""
        return compute_retry_delay(retry_count, task_id)
