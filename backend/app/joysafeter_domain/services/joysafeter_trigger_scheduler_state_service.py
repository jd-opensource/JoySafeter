from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
from app.joysafeter_domain.services.joysafeter_trigger_payload_sanitizer import sanitize_trigger_last_payload
from app.joysafeter_domain.services.joysafeter_trigger_runtime_gate import TriggerRuntimeGate
from app.joysafeter_shared.utils.cron import compute_next_run


class TriggerSchedulerStateService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        get_trigger: Optional[Callable[[uuid.UUID], Awaitable[Optional[JoySafeterTrigger]]]] = None,
        get_trigger_for_update: Optional[Callable[[uuid.UUID], Awaitable[Optional[JoySafeterTrigger]]]] = None,
        sync_config: Optional[Callable[[JoySafeterTrigger], None]] = None,
        next_run_or_pause: Optional[Callable[[JoySafeterTrigger], Awaitable[Optional[datetime]]]] = None,
        runtime_block_reason: Optional[Callable[[JoySafeterTrigger], Awaitable[Optional[str]]]] = None,
    ) -> None:
        self.db = db
        self._get_trigger = get_trigger
        self._get_trigger_for_update = get_trigger_for_update
        self._sync_config_cb = sync_config
        self._next_run_or_pause = next_run_or_pause
        self._runtime_block_reason = runtime_block_reason

    @staticmethod
    def _sync_config(trigger: JoySafeterTrigger) -> None:
        TriggerConfigPolicy.sync_config(trigger)

    async def get(self, trigger_id: uuid.UUID) -> Optional[JoySafeterTrigger]:
        if self._get_trigger is not None:
            return await self._get_trigger(trigger_id)
        result = await self.db.execute(
            select(JoySafeterTrigger).where(
                JoySafeterTrigger.id == trigger_id,
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, trigger_id: uuid.UUID) -> Optional[JoySafeterTrigger]:
        if self._get_trigger_for_update is not None:
            return await self._get_trigger_for_update(trigger_id)
        if self._get_trigger is not None:
            return await self._get_trigger(trigger_id)
        result = await self.db.execute(TriggerRuntimeGate.lock_stmt(trigger_id))
        return result.scalar_one_or_none()

    async def _owns_claim_or_release(self, trigger: JoySafeterTrigger, expected_locked_by: Optional[str]) -> bool:
        """Whether this worker still owns *trigger*'s claim.

        When another worker has taken over, commit to release the FOR UPDATE lock
        held by ``get_for_update`` before the caller bails out.
        """
        if expected_locked_by is None or trigger.locked_by == expected_locked_by:
            return True
        await self.db.commit()
        return False

    def sync_config(self, trigger: JoySafeterTrigger) -> None:
        if self._sync_config_cb is not None:
            self._sync_config_cb(trigger)
            return
        self._sync_config(trigger)

    async def claim_due_cron_triggers(
        self,
        *,
        worker_id: str,
        limit: int,
        lock_grace_sec: int = 120,
    ) -> Sequence[JoySafeterTrigger]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=lock_grace_sec)
        stmt = (
            select(JoySafeterTrigger)
            .where(
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.enabled.is_(True),
                JoySafeterTrigger.deleted_at.is_(None),
                JoySafeterTrigger.next_run_at.is_not(None),
                JoySafeterTrigger.next_run_at <= now,
                TriggerRuntimeGate.claimable_lock_filter(stale_before),
                TriggerRuntimeGate.live_project_filter(),
                TriggerRuntimeGate.live_agent_filter(),
                TriggerRuntimeGate.live_environment_filter(),
            )
            .order_by(JoySafeterTrigger.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.db.execute(stmt)
        triggers = list(result.scalars().all())
        for trigger in triggers:
            trigger.locked_by = worker_id
            trigger.locked_at = now
        await self.db.commit()
        return triggers

    async def release_claim(self, trigger_id: uuid.UUID, *, expected_locked_by: Optional[str] = None) -> None:
        conditions = [JoySafeterTrigger.id == trigger_id, JoySafeterTrigger.deleted_at.is_(None)]
        if expected_locked_by is not None:
            conditions.append(JoySafeterTrigger.locked_by == expected_locked_by)
        await self.db.execute(update(JoySafeterTrigger).where(*conditions).values(locked_by=None, locked_at=None))
        await self.db.commit()

    async def earliest_next_run(self, *, lock_grace_sec: int = 120) -> Optional[datetime]:
        stale_before = datetime.now(timezone.utc) - timedelta(seconds=lock_grace_sec)
        result = await self.db.execute(
            select(func.min(JoySafeterTrigger.next_run_at)).where(
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.enabled.is_(True),
                JoySafeterTrigger.deleted_at.is_(None),
                JoySafeterTrigger.next_run_at.is_not(None),
                TriggerRuntimeGate.claimable_lock_filter(stale_before),
                TriggerRuntimeGate.live_project_filter(),
                TriggerRuntimeGate.live_agent_filter(),
                TriggerRuntimeGate.live_environment_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def advance_after_fire(
        self,
        trigger_id: uuid.UUID,
        fired_slot: datetime,
        *,
        success: bool = True,
        record_attempt: bool = True,
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        expected_locked_by: Optional[str] = None,
    ) -> bool:
        trigger = await self.get_for_update(trigger_id)
        if trigger is None:
            return False
        if not await self._owns_claim_or_release(trigger, expected_locked_by):
            return False
        trigger.last_fired_slot = fired_slot
        trigger.locked_by = None
        trigger.locked_at = None
        trigger.slot_attempts = 0
        trigger.pending_slot_at = None
        if record_attempt:
            self.apply_attempt(
                trigger,
                success=success,
                task_id=task_id,
                session_id=session_id,
                error=error,
                payload=payload,
            )
        trigger.next_run_at = await self.next_run_or_pause(trigger)
        self.sync_config(trigger)
        await self.db.commit()
        return True

    async def record_fire_failure(
        self,
        trigger_id: uuid.UUID,
        fired_slot: datetime,
        *,
        error: str,
        transient: bool,
        expected_locked_by: Optional[str] = None,
    ) -> bool:
        from app.joysafeter_shared.config.settings import settings

        trigger = await self.get_for_update(trigger_id)
        if trigger is None:
            return False
        if not await self._owns_claim_or_release(trigger, expected_locked_by):
            return False
        now = datetime.now(timezone.utc)
        trigger.slot_attempts = (trigger.slot_attempts or 0) + 1
        trigger.pending_slot_at = fired_slot
        trigger.last_attempt_at = now
        trigger.last_error = error
        trigger.locked_by = None
        trigger.locked_at = None

        if transient and trigger.slot_attempts <= settings.scheduler_slot_max_retries:
            if self._runtime_block_reason is not None:
                block_reason = await self._runtime_block_reason(trigger)
            else:
                block_reason = await TriggerRuntimeGate(self.db).trigger_runtime_block_reason(trigger)
            if block_reason is not None:
                trigger.slot_attempts = 0
                trigger.pending_slot_at = None
                trigger.next_run_at = None
                self.sync_config(trigger)
                await self.db.commit()
                return False
            backoff = min(
                settings.scheduler_retry_backoff_cap_sec,
                settings.scheduler_retry_backoff_base_sec * (2 ** (trigger.slot_attempts - 1)),
            )
            trigger.next_run_at = now + timedelta(seconds=backoff)
            self.sync_config(trigger)
            await self.db.commit()
            return False

        trigger.consecutive_failures = (trigger.consecutive_failures or 0) + 1
        trigger.slot_attempts = 0
        trigger.pending_slot_at = None
        trigger.last_fired_slot = fired_slot
        dead_lettered = trigger.consecutive_failures >= settings.scheduler_failure_threshold
        if dead_lettered:
            trigger.enabled = False
            trigger.auto_disabled_at = now
            trigger.disabled_reason = (
                f"Auto-disabled after {trigger.consecutive_failures} consecutive fire failures: {error}"
            )
            trigger.next_run_at = None
        else:
            trigger.next_run_at = await self.next_run_or_pause(trigger)
        self.sync_config(trigger)
        await self.db.commit()
        return dead_lettered

    async def next_run_or_pause(self, trigger: JoySafeterTrigger) -> Optional[datetime]:
        if self._next_run_or_pause is not None:
            return await self._next_run_or_pause(trigger)
        if not trigger.enabled:
            return None
        if self._runtime_block_reason is not None:
            block_reason = await self._runtime_block_reason(trigger)
        else:
            block_reason = await TriggerRuntimeGate(self.db).trigger_runtime_block_reason(trigger)
        if block_reason is not None:
            return None
        if trigger.cron_expr:
            return compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")
        if trigger.run_at is not None and trigger.last_fired_slot is None:
            run_at = trigger.run_at if trigger.run_at.tzinfo else trigger.run_at.replace(tzinfo=timezone.utc)
            if run_at > datetime.now(timezone.utc):
                return run_at
        return None

    @staticmethod
    def apply_attempt(
        trigger: JoySafeterTrigger,
        *,
        success: Optional[bool],
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record trigger attempt bookkeeping.

        ``success=None`` is a neutral skipped delivery/run: stamp the attempt
        and payload for observability, but do not mutate success/failure state.
        """
        trigger.last_attempt_at = datetime.now(timezone.utc)
        if task_id is not None:
            trigger.last_task_id = task_id
        if session_id is not None:
            trigger.last_session_id = session_id
            if trigger.session_mode == "reuse":
                trigger.reusable_session_id = session_id
        if payload is not None:
            trigger.last_payload = sanitize_trigger_last_payload(payload)
        if success is True:
            trigger.last_success_at = trigger.last_attempt_at
            trigger.last_error = None
            trigger.consecutive_failures = 0
        elif success is False:
            trigger.last_error = error or "trigger fire failed"
            trigger.consecutive_failures = (trigger.consecutive_failures or 0) + 1

    async def mark_attempt(
        self,
        trigger: JoySafeterTrigger,
        *,
        success: Optional[bool],
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self.apply_attempt(
            trigger,
            success=success,
            task_id=task_id,
            session_id=session_id,
            error=error,
            payload=payload,
        )
        self.sync_config(trigger)
        await self.db.commit()
