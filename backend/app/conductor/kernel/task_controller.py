import asyncio
import logging
import uuid

from uuid_utils import uuid7

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
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT pg_try_advisory_lock(hashtext('task_recovery'))"))
            locked = result.scalar()
            if not locked:
                logger.info("Recovery lock held by another instance, skipping")
                return

            try:
                from app.conductor.lifespan import get_redis_coordinator
                coordinator = get_redis_coordinator()
                redis_available = coordinator is not None

                # Running tasks that exceeded their timeout -> failed
                recovered_result = await db.execute(text(
                    "UPDATE conductor_tasks SET status = 'failed',"
                    " error = 'Orchestrator restarted — task was running when process exited',"
                    " completed_at = NOW()"
                    " WHERE status = 'running'"
                    " AND started_at IS NOT NULL"
                    " AND started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                    " RETURNING id"
                ))
                recovered_tasks = recovered_result.all()

                # Stale pending tasks -> failed (only without Redis)
                if not redis_available:
                    stale_pending_result = await db.execute(text(
                        "UPDATE conductor_tasks SET status = 'failed',"
                        " error = 'Task was pending when orchestrator restarted',"
                        " completed_at = NOW()"
                        " WHERE status = 'pending'"
                        " AND created_at < NOW() - INTERVAL '5 minutes'"
                        " RETURNING id"
                    ))
                    stale_pending = stale_pending_result.all()
                else:
                    logger.warning("Skipping stale pending task cleanup — Redis configured")
                    stale_pending = []

                # Scheduling tasks -> pending (unconditional, no time filter)
                stale_scheduling_result = await db.execute(text(
                    "UPDATE conductor_tasks SET status = 'pending', started_at = NULL, sandbox_id = NULL,"
                    " retry_count = retry_count + 1"
                    " WHERE status = 'scheduling'"
                    " RETURNING id"
                ))
                stale_scheduling = stale_scheduling_result.all()

                # Provisioning sandboxes: 45min with Redis, 20min without
                provisioning_minutes = 45 if redis_available else 20
                stale_provisioning_result = await db.execute(
                    text(
                        "UPDATE conductor_sandboxes SET status = 'stopped', last_used_at = NOW()"
                        " WHERE status = 'provisioning'"
                        " AND created_at < NOW() - (:mins * INTERVAL '1 minute')"
                        " RETURNING id"
                    ),
                    {"mins": provisioning_minutes},
                )
                stale_provisioning = stale_provisioning_result.all()

                # Reset sessions stuck in 'rescheduling'
                stale_rescheduling_result = await db.execute(text(
                    "UPDATE conductor_sessions SET status = 'terminated',"
                    " stop_reason = '{\"type\": \"retries_exhausted\"}',"
                    " updated_at = NOW()"
                    " WHERE status = 'rescheduling'"
                    " AND updated_at < NOW() - INTERVAL '5 minutes'"
                    " RETURNING id"
                ))
                stale_rescheduling_sessions = stale_rescheduling_result.all()

                for row in stale_rescheduling_sessions:
                    sid = row[0]
                    await db.execute(
                        text(
                            "INSERT INTO conductor_session_events (id, session_id, event_type, payload, seq, created_at, processed_at)"
                            " VALUES (:evt_id, :sid, 'session.status_terminated',"
                            " '{\"stop_reason\":{\"type\":\"retries_exhausted\"}}',"
                            " (SELECT COALESCE(MAX(seq), 0) + 1 FROM conductor_session_events WHERE session_id = :sid),"
                            " NOW(), NOW())"
                        ),
                        {"evt_id": uuid7(), "sid": sid},
                    )

                # Reset sessions stuck in 'running' with no active tasks
                stale_running_result = await db.execute(text(
                    "UPDATE conductor_sessions SET status = 'idle',"
                    " stop_reason = '{\"type\": \"end_turn\"}',"
                    " updated_at = NOW()"
                    " WHERE status = 'running'"
                    " AND updated_at < NOW() - INTERVAL '5 minutes'"
                    " AND NOT EXISTS ("
                    "     SELECT 1 FROM conductor_tasks"
                    "     WHERE conductor_tasks.chat_session_id = conductor_sessions.id"
                    "     AND conductor_tasks.status IN ('pending', 'scheduling', 'running')"
                    " )"
                    " RETURNING id"
                ))
                stale_running_sessions = stale_running_result.all()

                for row in stale_running_sessions:
                    sid = row[0]
                    await db.execute(
                        text(
                            "INSERT INTO conductor_session_events (id, session_id, event_type, payload, seq, created_at, processed_at)"
                            " VALUES (:evt_id, :sid, 'session.status_idle',"
                            " '{\"stop_reason\":{\"type\":\"end_turn\"}}',"
                            " (SELECT COALESCE(MAX(seq), 0) + 1 FROM conductor_session_events WHERE session_id = :sid),"
                            " NOW(), NOW())"
                        ),
                        {"evt_id": uuid7(), "sid": sid},
                    )

                await db.commit()
                logger.info(
                    "Startup recovery complete: tasks_failed=%d pending_cleared=%d scheduling_reset=%d "
                    "provisioning_recovered=%d rescheduling_sessions_terminated=%d running_sessions_reset=%d "
                    "redis_available=%s",
                    len(recovered_tasks),
                    len(stale_pending),
                    len(stale_scheduling),
                    len(stale_provisioning),
                    len(stale_rescheduling_sessions),
                    len(stale_running_sessions),
                    redis_available,
                )
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(hashtext('task_recovery'))"))

    async def _check_overdue_tasks(self) -> None:
        from app.core.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            tx = await conn.begin()
            try:
                result = await conn.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('task_watchdog'))"))
                locked = result.scalar()
                if not locked:
                    return

                rows = (await conn.execute(text(
                    "SELECT id, sandbox_id, chat_session_id FROM conductor_tasks"
                    " WHERE status = 'running'"
                    " AND started_at IS NOT NULL"
                    " AND started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                ))).all()

                for row in rows:
                    task_id, sandbox_id, session_id = row[0], row[1], row[2]
                    logger.warning("Task %s exceeded timeout (sandbox=%s), marking timed out", task_id, sandbox_id)

                    await conn.execute(
                        text(
                            "UPDATE conductor_tasks SET status = 'timeout',"
                            " error = 'Task timed out (watchdog)',"
                            " completed_at = NOW()"
                            " WHERE id = :tid AND status = 'running'"
                        ),
                        {"tid": task_id},
                    )

                    if session_id is not None:
                        is_running = (await conn.execute(
                            text("SELECT EXISTS(SELECT 1 FROM conductor_sessions WHERE id = :sid AND status = 'running')"),
                            {"sid": session_id},
                        )).scalar()

                        if is_running:
                            await conn.execute(
                                text(
                                    "UPDATE conductor_sessions SET status = 'idle',"
                                    " stop_reason = '{\"type\": \"timeout\"}',"
                                    " updated_at = NOW()"
                                    " WHERE id = :sid AND status = 'running'"
                                ),
                                {"sid": session_id},
                            )
                            await conn.execute(
                                text(
                                    "INSERT INTO conductor_session_events (id, session_id, event_type, payload, seq, created_at, processed_at)"
                                    " VALUES (:evt_id, :sid, 'session.status_idle',"
                                    " '{\"stop_reason\":{\"type\":\"timeout\"}}',"
                                    " (SELECT COALESCE(MAX(seq), 0) + 1 FROM conductor_session_events WHERE session_id = :sid),"
                                    " NOW(), NOW())"
                                ),
                                {"evt_id": uuid7(), "sid": session_id},
                            )

                    logger.info("Timed-out task %s marked as timeout", task_id)

                await tx.commit()
            except Exception:
                await tx.rollback()
                raise

    async def _check_stuck_scheduling(self) -> None:
        from app.core.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            tx = await conn.begin()
            try:
                lock_result = await conn.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('task_scheduling_watchdog'))"))
                locked = lock_result.scalar()
                if not locked:
                    return

                result = await conn.execute(text(
                    "UPDATE conductor_tasks SET status = 'pending', started_at = NULL, sandbox_id = NULL,"
                    " retry_count = retry_count + 1"
                    " WHERE status = 'scheduling'"
                    " AND updated_at < NOW() - INTERVAL '2 minutes'"
                    " RETURNING id"
                ))
                rows = result.all()
                for row in rows:
                    task_id = row[0]
                    logger.warning("Task %s stuck in scheduling >2min, reset to pending and re-enqueued", task_id)

                await tx.commit()

                for row in rows:
                    await self._queue.push_to_global(row[0])
            except Exception:
                await tx.rollback()
                raise

    @staticmethod
    async def failover_or_fail_task(task_id: uuid.UUID, reason: str) -> "int | None":
        """Attempt to retry the task. Returns the retry_count (pre-increment) if retried, None if terminal/failed."""
        from app.core.database import AsyncSessionLocal
        from app.conductor.services.task_service import TaskService
        from app.conductor.services.session_service import SessionService
        from app.conductor.models.task import TaskStatus

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
                    # Transition session to idle since the task effectively finished
                    try:
                        await session_svc.update_session_status(
                            task.chat_session_id, "idle",
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
