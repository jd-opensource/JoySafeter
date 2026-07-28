"""Cron trigger poll loop (runs inside the worker service).

Each tick atomically claims due cron triggers (``FOR UPDATE SKIP LOCKED`` — safe
across any number of worker replicas), then for each claimed trigger submits a
task through the shared ``TaskSubmissionService`` — the exact path the HTTP API
uses. The task's ``idempotency_key`` is derived from the trigger id and the
aligned cron slot, so the task engine's unique constraint guarantees
exactly-once firing even if two workers race or a tick is retried.

The loop never runs the agent itself; it only decides *when* to submit. All
execution reliability (lease, owner_epoch fencing, watchdog reclaim, retry,
event-stream results) is inherited from the Rust orchestrator.

Reliability of the *fire decision* itself lives here:

- **Bounded backoff retry per slot.** A transient fire failure (timeout,
  admission rate-limit, transient service/DB error, half-done REPLACE cancel)
  keeps the same logical slot due via ``record_fire_failure`` and re-fires it on
  a later tick with an attempt-suffixed idempotency key. A permanent failure (or
  exhausted retries) abandons the slot and counts a consecutive failure.
- **Dead-letter / auto-disable.** After ``scheduler_failure_threshold``
  consecutive failures the trigger is auto-disabled with a loud alert, so it
  stops silently failing every slot forever.
- **Per-fire timeout.** Every fire is time-bounded so one hung fire can never
  wedge the whole sweep.
- **Adaptive sleep + LISTEN/NOTIFY.** The loop sleeps only until the nearest due
  slot (not a fixed interval) and is woken immediately by a Postgres NOTIFY when
  a trigger is created/updated. The poll remains the correctness backstop.
- **Heartbeat.** Per-tick metrics (claimed / fired / failed / max fire lag) are
  recorded on a module-level ``SchedulerHeartbeat`` for health inspection.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger, TriggerConcurrencyPolicy
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    render_prompt_template,
    render_session_key,
)
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_session_service import (
    SessionService,  # noqa: F401  (kept as a test monkeypatch target)
)
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_domain.triggers import get_provider
from app.joysafeter_shared.common.app_errors import AppError, RateLimitExceededError, ServiceUnavailableError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# Cancellation failure modes that leave a REPLACE-policy fire in a half-done
# state: the prior run was (or may have been) cancelled but a replacement was
# never dispatched. These are transient — a later tick retries the whole fire
# cleanly (by then the prior task is terminal, so get_active_tasks is empty).
_CANCEL_RETRYABLE_CODES = frozenset(
    {
        "TASK_CANCEL_REDIS_RELAY_FAILED",
        "TASK_CANCEL_STATE_SYNC_FAILED",
        "TASK_CANCEL_SESSION_SYNC_FAILED",
    }
)


def _is_transient_fire_error(exc: Exception) -> bool:
    """Whether a failed fire should be retried on the same slot with backoff."""
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, (RateLimitExceededError, ServiceUnavailableError)):
        return True
    if isinstance(exc, AppError):
        if exc.code in _CANCEL_RETRYABLE_CODES:
            return True
        return bool(getattr(exc, "retryable", False))
    return False


@dataclass
class SchedulerHeartbeat:
    """Liveness / throughput snapshot of the scheduler loop (for health checks)."""

    last_tick_at: Optional[datetime] = None
    last_claimed: int = 0
    total_fired: int = 0
    total_failed: int = 0
    max_fire_lag_sec: float = 0.0

    def mark_tick(self, *, claimed: int) -> None:
        self.last_tick_at = datetime.now(timezone.utc)
        self.last_claimed = claimed

    def mark_fire(self, *, success: bool, fire_lag_sec: float = 0.0) -> None:
        if success:
            self.total_fired += 1
            self.max_fire_lag_sec = max(self.max_fire_lag_sec, fire_lag_sec)
        else:
            self.total_failed += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_claimed": self.last_claimed,
            "total_fired": self.total_fired,
            "total_failed": self.total_failed,
            "max_fire_lag_sec": round(self.max_fire_lag_sec, 3),
        }


_HEARTBEAT = SchedulerHeartbeat()


def scheduler_heartbeat() -> SchedulerHeartbeat:
    """Return the process-wide scheduler heartbeat (for worker health checks)."""
    return _HEARTBEAT


@dataclass(frozen=True)
class _FireOutcome:
    """Result of processing one due cron trigger (no exception path)."""

    status: str  # "fired" | "deduped" | "skipped"
    task_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    payload: Optional[dict] = None


class SchedulerLoop:
    """Periodically claim due cron triggers and submit their tasks."""

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
        self._wake = asyncio.Event()
        self._listen_task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        logger.info("Scheduler loop started (worker=%s, interval=%ss)", self._worker_id, self._poll_interval)
        # LISTEN/NOTIFY is a latency optimization; the poll below is the
        # correctness backstop. It is unsupported through a pgbouncer transaction
        # pool, so skip it there and rely on polling.
        if settings.scheduler_notify_enabled and not getattr(settings, "database_pgbouncer", False):
            self._listen_task = asyncio.create_task(self._listen(), name="joysafeter-scheduler-listen")
        try:
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
                await self._sleep_until_wake()
        finally:
            if self._listen_task is not None:
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except (asyncio.CancelledError, Exception):
                    pass
        logger.info("Scheduler loop stopped (worker=%s)", self._worker_id)

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()

    async def _sleep_until_wake(self) -> None:
        """Sleep until the nearest due slot, a NOTIFY wake, or stop.

        The sleep is bounded by ``[scheduler_min_sleep_sec, poll_interval]`` so a
        far-future schedule doesn't sleep forever (poll backstop) and a
        just-passed slot re-ticks promptly.
        """
        try:
            async with AsyncSessionLocal() as db:
                nxt = await JoySafeterTriggerService(db).earliest_next_run(lock_grace_sec=self._lock_grace)
        except Exception:
            nxt = None
        if nxt is None:
            sleep = float(self._poll_interval)
        else:
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            delta = (nxt - datetime.now(timezone.utc)).total_seconds()
            sleep = max(float(settings.scheduler_min_sleep_sec), min(float(self._poll_interval), delta))

        self._wake.clear()
        stop_task = asyncio.ensure_future(self._stopping.wait())
        wake_task = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({stop_task, wake_task}, timeout=sleep, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_task.cancel()
            wake_task.cancel()

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, _payload: str) -> None:
        # Runs inside the event loop (asyncpg listener callback); waking is cheap.
        self._wake.set()

    async def _listen(self) -> None:
        """Hold a Postgres LISTEN on the wake channel; reconnect with backoff.

        Any failure is non-fatal — the poll loop still fires every slot; NOTIFY
        only removes up-to-``poll_interval`` seconds of latency.
        """
        from app.joysafeter_shared.database import engine

        channel = settings.scheduler_notify_channel
        backoff = 1.0
        while not self._stopping.is_set():
            conn = None
            try:
                conn = await engine.connect()
                raw = await conn.get_raw_connection()
                asyncpg_conn = raw.driver_connection
                if asyncpg_conn is None:
                    raise RuntimeError("no raw asyncpg connection available for LISTEN")
                await asyncpg_conn.add_listener(channel, self._on_notify)
                logger.info("Scheduler LISTEN active on channel %s", channel)
                backoff = 1.0
                while not self._stopping.is_set():
                    await asyncio.sleep(1.0)
                    if asyncpg_conn.is_closed():
                        raise RuntimeError("LISTEN connection closed")
                try:
                    await asyncpg_conn.remove_listener(channel, self._on_notify)
                except Exception:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "Scheduler LISTEN unavailable (%s); polling remains the backstop, retrying in %.0fs",
                    exc,
                    min(30.0, backoff),
                )
                await asyncio.sleep(min(30.0, backoff))
                backoff *= 2
            finally:
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:
                        pass

    async def _tick(self) -> None:
        async with AsyncSessionLocal() as db:
            triggers = await JoySafeterTriggerService(db).claim_due_cron_triggers(
                worker_id=self._worker_id,
                limit=self._claim_batch,
                lock_grace_sec=self._lock_grace,
            )
        _HEARTBEAT.mark_tick(claimed=len(triggers))
        if not triggers:
            return
        logger.info("Scheduler claimed %d due cron trigger(s)", len(triggers))
        # Process each in its own session so one failure can't poison the batch.
        for trigger in triggers:
            # A slot being retried carries pending_slot_at; otherwise the due slot
            # is next_run_at. Keeping the slot stable keeps the idempotency key
            # (and thus exactly-once-per-slot) coherent across retries.
            fired_slot = trigger.pending_slot_at or trigger.next_run_at or datetime.now(timezone.utc)
            try:
                outcome = await asyncio.wait_for(
                    self._fire(trigger, fired_slot),
                    timeout=settings.scheduler_fire_timeout_sec,
                )
            except Exception as exc:
                transient = _is_transient_fire_error(exc)
                async with AsyncSessionLocal() as db:
                    dead_lettered = await JoySafeterTriggerService(db).record_fire_failure(
                        trigger.id,
                        fired_slot,
                        error=str(exc) or exc.__class__.__name__,
                        transient=transient,
                    )
                _HEARTBEAT.mark_fire(success=False)
                if dead_lettered:
                    log_boundary_failure(
                        logger,
                        boundary="scheduler_loop",
                        code="SCHEDULER_TRIGGER_AUTODISABLED",
                        message="Trigger auto-disabled after repeated fire failures",
                        operation="scheduler_fire",
                        error=exc,
                        data={"worker_id": self._worker_id, "trigger_id": str(trigger.id)},
                        source="worker",
                    )
                else:
                    log_boundary_failure(
                        logger,
                        boundary="scheduler_loop",
                        code="SCHEDULER_FIRE_FAILED",
                        message="Scheduler failed to fire cron trigger",
                        operation="scheduler_fire",
                        error=exc,
                        data={
                            "worker_id": self._worker_id,
                            "trigger_id": str(trigger.id),
                            "transient": transient,
                        },
                        source="worker",
                    )
                continue
            # Fired, deduped, or skipped — all advance the slot. Archive self-heal
            # inside advance_after_fire pauses (next_run_at=None) any trigger whose
            # project/agent/environment was archived while this fire was in flight.
            # A skip (e.g. FORBID with a prior run still active) advances the slot
            # but is neither a success nor a failure, so it records no attempt.
            async with AsyncSessionLocal() as db:
                svc = JoySafeterTriggerService(db)
                if outcome.status == "skipped":
                    await svc.advance_after_fire(trigger.id, fired_slot, record_attempt=False)
                else:
                    await svc.advance_after_fire(
                        trigger.id,
                        fired_slot,
                        success=True,
                        task_id=outcome.task_id,
                        session_id=outcome.session_id,
                        payload=outcome.payload,
                    )
            fire_lag = (datetime.now(timezone.utc) - fired_slot).total_seconds()
            _HEARTBEAT.mark_fire(success=outcome.status != "skipped", fire_lag_sec=fire_lag)

    async def _fire(self, trigger: JoySafeterTrigger, fired_slot: datetime) -> _FireOutcome:
        async with AsyncSessionLocal() as db:
            submission = TaskSubmissionService(db)
            trigger_svc = JoySafeterTriggerService(db)

            block_reason = await trigger_svc.trigger_runtime_block_reason(trigger)
            if block_reason is not None:
                logger.info("Trigger %s skipped before fire: %s", trigger.id, block_reason)
                return _FireOutcome(status="skipped")

            # Exactly-once firing per (slot, attempt): the idempotency key encodes
            # the slot instant; a retry (slot_attempts > 0) gets an attempt-suffixed
            # key so it re-fires instead of deduping against the prior FAILED task.
            # The INSERT unique constraint in create_task remains the race-proof
            # arbiter; this pre-check makes crash replay idempotent before
            # concurrency/admission gates can misclassify the already-created run.
            provider = get_provider("cron")
            attempt = getattr(trigger, "slot_attempts", 0) or 0
            idempotency_key = provider.idempotency_key(trigger, fired_slot=fired_slot, attempt=attempt)
            existing_task = await submission.tasks.get_by_idempotency_key(
                idempotency_key,
                project_id=trigger.project_id,
            )
            if existing_task is not None:
                logger.info(
                    "Trigger %s slot %s already fired as task %s; no duplicate session",
                    trigger.id,
                    fired_slot.isoformat(),
                    existing_task.id,
                )
                return _FireOutcome(
                    status="deduped",
                    task_id=existing_task.id,
                    session_id=getattr(existing_task, "chat_session_id", None),
                    payload={"deduped": True, "cron": {"fired_at": fired_slot.isoformat()}},
                )

            # Concurrency policy: decide whether this fire may proceed.
            policy = trigger.concurrency_policy
            if policy in (TriggerConcurrencyPolicy.FORBID.value, TriggerConcurrencyPolicy.REPLACE.value):
                active = await trigger_svc.get_active_tasks(trigger.id)
                if active:
                    if policy == TriggerConcurrencyPolicy.FORBID.value:
                        logger.info(
                            "Trigger %s: prior run still active (%d task(s)); skipping fire (forbid)",
                            trigger.id,
                            len(active),
                        )
                        return _FireOutcome(status="skipped")
                    # replace: terminate the prior run(s) before firing a new one.
                    # Shared cancellation service so the DB transition AND the Redis
                    # cancel command (which actually stops the running sandbox) always
                    # happen together — a bare status flip left the old run executing.
                    canceller = TaskCancellationService(db)
                    for task in active:
                        await canceller.cancel(
                            task,
                            reason=f"Replaced by trigger {trigger.id} slot {fired_slot.isoformat()}",
                        )
                    logger.info("Trigger %s: replaced %d active task(s)", trigger.id, len(active))

            # Admission control — identical gate to the HTTP endpoint. Service
            # principals (a trigger) are bounded by the project quota only.
            await submission.enforce_admission(
                project_id=trigger.project_id,
                user_id=trigger.user_id,
                enforce_user_quota=False,
            )

            # Resolve the agent the trigger targets.
            agent = await JoySafeterAgentService(db).get_agent(trigger.agent_id, project_id=trigger.project_id)
            if agent is None:
                logger.warning("Trigger %s targets missing agent %s; skipping", trigger.id, trigger.agent_id)
                return _FireOutcome(status="skipped")
            if getattr(agent, "archived_at", None) is not None:
                logger.warning("Trigger %s targets archived agent %s; skipping", trigger.id, trigger.agent_id)
                return _FireOutcome(status="skipped")

            environment_ref = trigger.environment_ref or getattr(agent, "environment_ref", None)
            if environment_ref:
                environment = await EnvironmentService(db).get_environment_by_ref(
                    environment_ref,
                    project_id=trigger.project_id,
                )
                if environment is None:
                    logger.warning("Trigger %s targets missing environment %s; skipping", trigger.id, environment_ref)
                    return _FireOutcome(status="skipped")
                if getattr(environment, "archived_at", None) is not None:
                    logger.warning("Trigger %s targets archived environment %s; skipping", trigger.id, environment_ref)
                    return _FireOutcome(status="skipped")

            payload = provider.build_payload(trigger, fired_slot=fired_slot)
            rendered_prompt = render_prompt_template(trigger.prompt_template, payload)
            result = await AgentTriggerExecutor(db).run(
                AgentTriggerRunConfig(
                    agent=agent,
                    name=trigger.name,
                    source=f"trigger:cron:{trigger.id}",
                    prompt=rendered_prompt,
                    system_prompt=trigger.system_prompt,
                    environment_ref=environment_ref,
                    timeout_sec=trigger.timeout_sec,
                    max_retries=trigger.max_retries,
                    project_id=trigger.project_id,
                    user_id=trigger.user_id,
                    org_id=trigger.org_id,
                    idempotency_key=idempotency_key,
                    session_mode=getattr(trigger, "session_mode", "fresh"),
                    pinned_session_id=getattr(trigger, "pinned_session_id", None),
                    reusable_session_id=getattr(trigger, "reusable_session_id", None),
                    session_key=render_session_key(getattr(trigger, "session_key", None), payload),
                    trigger_id=trigger.id,
                    metadata={"trigger_id": str(trigger.id), "trigger_type": "cron"},
                ),
                enforce_user_quota=False,
            )
            if result.created:
                logger.info("Trigger %s fired task %s (slot=%s)", trigger.id, result.task.id, fired_slot.isoformat())
            else:
                logger.info(
                    "Trigger %s slot %s already fired (idempotent); no duplicate task",
                    trigger.id,
                    fired_slot.isoformat(),
                )
            return _FireOutcome(
                status="fired" if result.created else "deduped",
                task_id=result.task.id,
                session_id=result.session.id,
                payload=payload,
            )
