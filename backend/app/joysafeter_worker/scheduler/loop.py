"""Cron scheduler poll loop (runs inside the worker service).

Each tick atomically claims due schedules (``FOR UPDATE SKIP LOCKED`` — safe
across any number of worker replicas), then for each claimed schedule submits a
task through the shared ``TaskSubmissionService`` — the exact path the HTTP API
uses. The task's ``idempotency_key`` is derived from the schedule id and the
aligned cron slot, so the task engine's unique constraint guarantees
exactly-once firing even if two workers race or a tick is retried.

The loop never runs the agent itself; it only decides *when* to submit. All
execution reliability (lease, owner_epoch fencing, watchdog reclaim, retry,
event-stream results) is inherited from the Rust orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule, ScheduleConcurrencyPolicy
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# Cancellation failure modes that leave a REPLACE-policy fire in a half-done
# state: the prior run was (or may have been) cancelled but a replacement was
# never dispatched. Keeping the slot due lets a later tick retry the whole
# fire — by then the prior task is terminal, so get_active_tasks is empty and
# the replacement dispatches cleanly. Advancing instead would silently skip
# the slot after having killed the prior run.
_CANCEL_RETRYABLE_CODES = frozenset(
    {
        "TASK_CANCEL_REDIS_RELAY_FAILED",
        "TASK_CANCEL_STATE_SYNC_FAILED",
        "TASK_CANCEL_SESSION_SYNC_FAILED",
    }
)


def _should_retry_same_slot(exc: Exception) -> bool:
    return isinstance(exc, AppError) and exc.code in _CANCEL_RETRYABLE_CODES


class SchedulerLoop:
    """Periodically claim due schedules and submit their tasks."""

    def __init__(
        self,
        *,
        poll_interval_sec: int = 15,
        claim_batch: int = 50,
        lock_grace_sec: int = 120,
        worker_id: Optional[str] = None,
    ) -> None:
        self._poll_interval = poll_interval_sec
        self._claim_batch = claim_batch
        self._lock_grace = lock_grace_sec
        self._worker_id = worker_id or f"{socket.gethostname()}:sched:{uuid.uuid4().hex[:8]}"
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        logger.info("Scheduler loop started (worker=%s, interval=%ss)", self._worker_id, self._poll_interval)
        while not self._stopping.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="scheduler_loop",
                    code="SCHEDULER_TICK_FAILED",
                    message="Scheduler tick failed",
                    operation="scheduler_tick",
                    error=exc,
                    data={"worker_id": self._worker_id},
                    source="worker",
                )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("Scheduler loop stopped (worker=%s)", self._worker_id)

    async def stop(self) -> None:
        self._stopping.set()

    async def _tick(self) -> None:
        async with AsyncSessionLocal() as db:
            schedules = await JoySafeterScheduleService(db).claim_due_schedules(
                worker_id=self._worker_id,
                limit=self._claim_batch,
                lock_grace_sec=self._lock_grace,
            )
        if not schedules:
            return
        logger.info("Scheduler claimed %d due schedule(s)", len(schedules))
        # Process each in its own session so one failure can't poison the batch.
        for schedule in schedules:
            fired_slot = schedule.next_run_at or datetime.now(timezone.utc)
            retry_same_slot = False
            try:
                await self._fire(schedule, fired_slot)
            except Exception as exc:
                retry_same_slot = _should_retry_same_slot(exc)
                log_boundary_failure(
                    logger,
                    boundary="scheduler_loop",
                    code="SCHEDULER_FIRE_FAILED",
                    message="Scheduler failed to fire schedule",
                    operation="scheduler_fire",
                    error=exc,
                    data={"worker_id": self._worker_id, "schedule_id": str(schedule.id)},
                    source="worker",
                )
            finally:
                async with AsyncSessionLocal() as db:
                    schedule_svc = JoySafeterScheduleService(db)
                    if retry_same_slot:
                        # The previous run is still active and was not safely
                        # cancelled. Keep the current slot due so a later tick
                        # can retry the replace cancellation instead of silently
                        # dropping this fire.
                        await schedule_svc.release_claim(schedule.id)
                    else:
                        # Release the lock and advance so the schedule neither
                        # stays stuck nor immediately re-fires the same slot.
                        await schedule_svc.advance_after_fire(schedule.id, fired_slot)

    async def _fire(self, schedule: JoySafeterSchedule, fired_slot: datetime) -> None:
        async with AsyncSessionLocal() as db:
            submission = TaskSubmissionService(db)
            schedule_svc = JoySafeterScheduleService(db)

            # Concurrency policy: decide whether this fire may proceed.
            policy = schedule.concurrency_policy
            if policy in (ScheduleConcurrencyPolicy.FORBID.value, ScheduleConcurrencyPolicy.REPLACE.value):
                active = await schedule_svc.get_active_tasks(schedule.id)
                if active:
                    if policy == ScheduleConcurrencyPolicy.FORBID.value:
                        logger.info(
                            "Schedule %s: prior run still active (%d task(s)); skipping fire (forbid)",
                            schedule.id,
                            len(active),
                        )
                        return
                    # replace: terminate the prior run(s) before firing a new one.
                    # Shared cancellation service so the DB transition AND the Redis
                    # cancel command (which actually stops the running sandbox) always
                    # happen together — a bare status flip left the old run executing.
                    canceller = TaskCancellationService(db)
                    for task in active:
                        await canceller.cancel(
                            task,
                            reason=f"Replaced by schedule {schedule.id} slot {fired_slot.isoformat()}",
                        )
                    logger.info("Schedule %s: replaced %d active task(s)", schedule.id, len(active))

            # Admission control — identical gate to the HTTP endpoint. Service
            # principals (a schedule) are bounded by the project quota only.
            await submission.enforce_admission(
                project_id=schedule.project_id,
                user_id=schedule.user_id,
                enforce_user_quota=False,
            )

            # Resolve the agent the schedule targets.
            agent = await JoySafeterAgentService(db).get_agent(schedule.agent_id, project_id=schedule.project_id)
            if agent is None:
                logger.warning("Schedule %s targets missing agent %s; skipping", schedule.id, schedule.agent_id)
                return
            if getattr(agent, "archived_at", None) is not None:
                logger.warning("Schedule %s targets archived agent %s; skipping", schedule.id, schedule.agent_id)
                return

            # Fresh session per fire — each scheduled run is its own conversation,
            # sidestepping the one-active-task-per-session constraint entirely.
            environment_ref = schedule.environment_ref or getattr(agent, "environment_ref", None)
            environment = None
            if environment_ref:
                environment = await EnvironmentService(db).get_environment_by_ref(
                    environment_ref,
                    project_id=schedule.project_id,
                )
                if environment is None:
                    logger.warning("Schedule %s targets missing environment %s; pausing", schedule.id, environment_ref)
                    return
                if getattr(environment, "archived_at", None) is not None:
                    logger.warning("Schedule %s targets archived environment %s; pausing", schedule.id, environment_ref)
                    return

            # Exactly-once firing: pre-check the idempotency key before creating
            # the auto session. The INSERT unique constraint in create_task still
            # remains the race-proof arbiter, but this avoids orphan-prone
            # create-then-delete compensation on ordinary retries.
            slot_epoch = int(fired_slot.timestamp())
            idempotency_key = f"sched:{schedule.id}:{slot_epoch}"
            existing_task = await submission.tasks.get_by_idempotency_key(
                idempotency_key,
                project_id=schedule.project_id,
            )
            if existing_task is not None:
                logger.info(
                    "Schedule %s slot %s already fired as task %s; no duplicate session",
                    schedule.id,
                    fired_slot.isoformat(),
                    existing_task.id,
                )
                return

            session_svc = SessionService(db)
            session = await session_svc.create_session(
                agent_id=agent.id,
                title=f"Scheduled: {schedule.name}",
                environment_ref=environment_ref,
                agent_version=getattr(agent, "version", None),
                agent_snapshot=JoySafeterAgentService.build_execution_snapshot(
                    agent,
                    environment=environment,
                    environment_ref=environment_ref,
                ),
                project_id=schedule.project_id,
            )

            task, created = await submission.create_and_dispatch(
                agent_id=agent.id,
                prompt=schedule.prompt,
                system_prompt=schedule.system_prompt,
                chat_session_id=session.id,
                session_svc=session_svc,
                timeout_sec=schedule.timeout_sec,
                max_retries=schedule.max_retries,
                project_id=schedule.project_id,
                user_id=schedule.user_id,
                org_id=schedule.org_id,
                idempotency_key=idempotency_key,
                schedule_id=schedule.id,
                auto_created_session_id=session.id,
                enforce_admission=False,
                enforce_user_quota=False,
            )
            if created:
                logger.info("Schedule %s fired task %s (slot=%s)", schedule.id, task.id, fired_slot.isoformat())
            else:
                logger.info(
                    "Schedule %s slot %s already fired (idempotent); no duplicate task",
                    schedule.id,
                    fired_slot.isoformat(),
                )
