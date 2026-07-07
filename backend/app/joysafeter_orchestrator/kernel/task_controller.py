import asyncio
import logging
import uuid

from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.retry import compute_retry_delay

logger = logging.getLogger(__name__)


class TaskController:
    def __init__(self, queue):
        self._queue = queue

    async def run(self) -> None:
        logger.info("TaskController watchdog started (60s interval)")
        while True:
            await asyncio.sleep(60)
            await self._run_watchdog_iteration()

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
            await self._run_lease_iteration()

    async def _run_watchdog_iteration(self) -> None:
        try:
            await self._check_overdue_tasks()
        except Exception as e:
            self._log_boundary_failure(
                code="TASK_CONTROLLER_OVERDUE_CHECK_FAILED",
                message="Overdue task check failed",
                operation="check_overdue_tasks",
                error=e,
            )
        try:
            await self._check_stuck_scheduling()
        except Exception as e:
            self._log_boundary_failure(
                code="TASK_CONTROLLER_STUCK_SCHEDULING_CHECK_FAILED",
                message="Stuck scheduling check failed",
                operation="check_stuck_scheduling",
                error=e,
            )
        try:
            await self._scan_pending_tasks()
        except Exception as e:
            self._log_boundary_failure(
                code="TASK_CONTROLLER_PENDING_SCAN_FAILED",
                message="Pending task scanner failed",
                operation="scan_pending_tasks",
                error=e,
            )

    async def _run_lease_iteration(self) -> None:
        try:
            await self._renew_own_leases()
        except Exception as e:
            self._log_boundary_failure(
                code="TASK_CONTROLLER_LEASE_RENEWAL_FAILED",
                message="Lease renewal failed",
                operation="renew_own_leases",
                error=e,
            )
        try:
            await self._reclaim_expired_leases()
        except Exception as e:
            self._log_boundary_failure(
                code="TASK_CONTROLLER_LEASE_RECLAIM_FAILED",
                message="Lease reclaim scan failed",
                operation="reclaim_expired_leases",
                error=e,
            )

    @staticmethod
    def _log_boundary_failure(
        *,
        code: str,
        message: str,
        operation: str,
        error: Exception | None = None,
        data: dict[str, object] | None = None,
        retryable: bool = True,
        user_action: str | None = "retry",
    ) -> None:
        logger.warning(
            message,
            extra={
                "error": async_boundary_error_payload(
                    code=code,
                    message=message,
                    boundary="task_controller",
                    operation=operation,
                    data=data,
                    detail=error.__class__.__name__ if error is not None else None,
                    retryable=retryable,
                    user_action=user_action,
                )
            },
            exc_info=error is not None,
        )

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
                    self._log_boundary_failure(
                        code="TASK_LEASE_EXPIRED_RECLAIMING",
                        message="Task lease expired, reclaiming",
                        operation="reclaim_expired_task_lease",
                        data={"task_id": str(task_id)},
                    )
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

                # Scheduling tasks -> pending/fail on startup. These rows were
                # interrupted before reaching a sandbox; enqueue successful
                # resets immediately because the pending scan above already ran.
                stale_scheduling_result = await db.execute(
                    text("SELECT id, retry_count, max_retries FROM joysafeter_tasks WHERE status = 'scheduling'")
                )
                stale_scheduling = stale_scheduling_result.all()
                stale_scheduling_requeued = 0
                stale_scheduling_failed = 0
                for row in stale_scheduling:
                    task_id = row[0]
                    retry_count = row[1] or 0
                    max_retries = row[2] or 3
                    if retry_count >= max_retries:
                        await task_svc.update_task_error(
                            task_id,
                            "Retries exhausted while recovering scheduling task on startup",
                            TaskStatus.FAILED,
                        )
                        stale_scheduling_failed += 1
                    elif await task_svc.increment_retry(task_id):
                        await self._queue.push_to_global(task_id)
                        stale_scheduling_requeued += 1

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
                        " AND NOT EXISTS ("
                        "     SELECT 1 FROM joysafeter_tasks"
                        "     WHERE joysafeter_tasks.chat_session_id = joysafeter_sessions.id"
                        "     AND joysafeter_tasks.status IN ('pending', 'scheduling', 'running')"
                        " )"
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
                    "scheduling_requeued=%d scheduling_failed=%d provisioning_recovered=%d "
                    "rescheduling_sessions_terminated=%d running_sessions_reset=%d redis_available=%s",
                    len(recovered_tasks),
                    len(pending_tasks),
                    len(stale_scheduling),
                    stale_scheduling_requeued,
                    stale_scheduling_failed,
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
        from app.joysafeter_orchestrator.services import SessionService, TaskService
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

                for row in rows:
                    task_id, sandbox_id, session_id = row[0], row[1], row[2]
                    self._log_boundary_failure(
                        code="TASK_WATCHDOG_TIMEOUT",
                        message="Task exceeded watchdog timeout",
                        operation="mark_overdue_task_timeout",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id or ""),
                            "session_id": str(session_id or ""),
                        },
                    )

                    timeout_updated = await task_svc.update_task_error(
                        task_id,
                        "Task timed out (watchdog)",
                        TaskStatus.TIMEOUT,
                    )
                    if not timeout_updated:
                        self._log_boundary_failure(
                            code="TASK_WATCHDOG_TIMEOUT_WRITE_RACE",
                            message="Task watchdog timeout write lost CAS/status race",
                            operation="mark_overdue_task_timeout",
                            data={
                                "task_id": str(task_id),
                                "sandbox_id": str(sandbox_id or ""),
                                "session_id": str(session_id or ""),
                            },
                            retryable=False,
                            user_action="refresh",
                        )
                        continue

                    if session_id is not None:
                        session_svc = SessionService(db)
                        try:
                            idle_updated = await session_svc.update_session_status_for_task_event(
                                session_id,
                                SessionStatus.IDLE.value,
                                task_id,
                                stop_reason={"type": "timeout"},
                            )
                            if idle_updated:
                                await session_svc.send_event(
                                    session_id,
                                    "session.status_idle",
                                    {"task_id": str(task_id), "stop_reason": {"type": "timeout"}},
                                )
                        except Exception:
                            logger.debug(
                                "Could not transition timed-out task %s session to idle", task_id, exc_info=True
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
                        self._log_boundary_failure(
                            code="TASK_CONTROLLER_STUCK_SCHEDULING_RETRIES_EXHAUSTED",
                            message="Task stuck in scheduling and retries exhausted; marking failed",
                            operation="mark_stuck_scheduling_failed",
                            data={
                                "task_id": str(task_id),
                                "retry_count": retry_count,
                                "max_retries": max_retries,
                            },
                            retryable=False,
                            user_action="contact_support",
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
    async def failover_or_fail_task(
        task_id: uuid.UUID, reason: str, expected_epoch: "int | None" = None
    ) -> "int | None":
        """Attempt to retry the task. Returns the retry_count (pre-increment) if retried, None if terminal/failed.

        When ``expected_epoch`` is supplied, the call is fenced: if the task's
        current ``owner_epoch`` has advanced past it, the caller is a zombie whose
        task was already reclaimed and re-run — the failover is dropped so it
        cannot retry/fail a task a new owner now holds.
        """
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import SessionService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if not task:
                try:
                    await svc.update_task_error(task_id, reason, TaskStatus.FAILED)
                except Exception as e:
                    TaskController._log_boundary_failure(
                        code="TASK_FAILOVER_MARK_FAILED",
                        message="Failed to mark missing task as failed",
                        operation="failover_mark_missing_task_failed",
                        error=e,
                        data={"task_id": str(task_id)},
                    )
                return None

            if expected_epoch is not None and task.owner_epoch != expected_epoch:
                TaskController._log_boundary_failure(
                    code="TASK_CONTROLLER_STALE_FAILOVER_SKIPPED",
                    message="Stale failover skipped because task was reclaimed by another owner",
                    operation="failover_or_fail_task",
                    data={
                        "task_id": str(task_id),
                        "expected_epoch": expected_epoch,
                        "current_epoch": task.owner_epoch,
                    },
                    retryable=False,
                    user_action=None,
                )
                return None

            status = TaskStatus(task.status)
            if status.is_terminal():
                TaskController._log_boundary_failure(
                    code="TASK_CONTROLLER_TERMINAL_FAILOVER_SKIPPED",
                    message="Task already terminal; skipping failover",
                    operation="failover_or_fail_task",
                    data={"task_id": str(task_id), "status": status.value},
                    retryable=False,
                    user_action=None,
                )
                return None

            # If the task already emitted or persisted final output, it
            # effectively completed before the sandbox died. Mark it completed
            # instead of retrying; if the process crashed after writing
            # task.output but before sending agent.message, repair the missing
            # chat event first.
            if task.chat_session_id:
                session_svc = SessionService(db)
                has_agent_output = await session_svc.task_has_agent_output(task_id, task.chat_session_id)
                persisted_output = (task.output or "").strip()
                if has_agent_output or persisted_output:
                    logger.info(
                        "Task %s already produced output before sandbox death, marking completed",
                        task_id,
                    )
                    await session_svc.repair_missing_agent_message(task.chat_session_id, task_id, task.output)
                    ok = await svc.update_task_status(task_id, TaskStatus.COMPLETED, expected_epoch=expected_epoch)
                    if not ok:
                        TaskController._log_boundary_failure(
                            code="TASK_CONTROLLER_COMPLETE_AFTER_OUTPUT_CAS_CONFLICT",
                            message="CAS conflict marking task completed after output",
                            operation="complete_task_after_recovered_output",
                            data={
                                "task_id": str(task_id),
                                "session_id": str(task.chat_session_id),
                                "expected_epoch": expected_epoch,
                            },
                            retryable=False,
                            user_action=None,
                        )
                        return None
                    # Transition session to idle since the task effectively finished.
                    try:
                        idle_updated = await session_svc.update_session_status_for_task_event(
                            task.chat_session_id,
                            "idle",
                            task_id,
                            stop_reason={"type": "end_turn"},
                        )
                        if idle_updated:
                            await session_svc.send_event(
                                task.chat_session_id,
                                "session.status_idle",
                                {"task_id": str(task_id), "stop_reason": {"type": "end_turn"}},
                            )
                    except Exception:
                        pass
                    return None

            if task.retry_count < task.max_retries:
                count = task.retry_count
                ok = await svc.increment_retry(task_id, expected_epoch=expected_epoch)
                if ok:
                    return count
                else:
                    TaskController._log_boundary_failure(
                        code="TASK_CONTROLLER_RETRY_INCREMENT_CAS_CONFLICT",
                        message="CAS conflict incrementing task retry",
                        operation="increment_task_retry",
                        data={"task_id": str(task_id), "expected_epoch": expected_epoch},
                        retryable=False,
                        user_action=None,
                    )
                    return None

            failed = False
            try:
                failed = await svc.update_task_error(task_id, reason, TaskStatus.FAILED, expected_epoch=expected_epoch)
            except Exception as e:
                TaskController._log_boundary_failure(
                    code="TASK_FAILOVER_MARK_FAILED",
                    message="Failed to mark task as failed during failover",
                    operation="failover_mark_task_failed",
                    error=e,
                    data={"task_id": str(task_id), "expected_epoch": expected_epoch},
                )
            if failed and task.chat_session_id:
                try:
                    session_svc = SessionService(db)
                    stop_reason = {"type": "retries_exhausted"}
                    idle_updated = await session_svc.update_session_status_for_task_event(
                        task.chat_session_id,
                        "idle",
                        task_id,
                        stop_reason=stop_reason,
                    )
                    if idle_updated:
                        await session_svc.send_event(
                            task.chat_session_id,
                            "session.status_idle",
                            {"task_id": str(task_id), "stop_reason": stop_reason},
                        )
                except Exception:
                    logger.debug("Could not transition exhausted task %s session to idle", task_id, exc_info=True)
            return None

    @staticmethod
    def compute_retry_delay(retry_count: int, task_id: uuid.UUID) -> float:
        """Compute retry delay in seconds, matching Rust TaskController::compute_retry_delay."""
        return compute_retry_delay(retry_count, task_id)
