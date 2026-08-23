from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
from app.joysafeter_domain.services.joysafeter_trigger_runtime_gate import TriggerRuntimeGate
from app.joysafeter_domain.services.joysafeter_trigger_scheduler_state_service import TriggerSchedulerStateService
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.ids import AgentId, SessionId, TaskId, TriggerId

_NON_TERMINAL_STATUSES = [s.value for s in JoySafeterTaskStatus if s not in JOYSAFETER_TERMINAL_STATUSES]


class JoySafeterTriggerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _scheduler_state(self) -> TriggerSchedulerStateService:
        next_run_or_pause = None
        if type(self)._next_run_or_pause is not JoySafeterTriggerService._next_run_or_pause:
            next_run_or_pause = self._next_run_or_pause
        runtime_block_reason = None
        if type(self).trigger_runtime_block_reason is not JoySafeterTriggerService.trigger_runtime_block_reason:
            runtime_block_reason = self.trigger_runtime_block_reason
        get_trigger_for_update = None
        if hasattr(self.db, "execute"):

            async def get_trigger_for_update(trigger_id: TriggerId) -> Optional[JoySafeterTrigger]:
                return await self._get_for_update(trigger_id)

        return TriggerSchedulerStateService(
            self.db,
            get_trigger=lambda trigger_id: self.get(trigger_id),
            get_trigger_for_update=get_trigger_for_update,
            sync_config=self._sync_config,
            next_run_or_pause=next_run_or_pause,
            runtime_block_reason=runtime_block_reason,
        )

    async def resolve_runnable_target(
        self,
        *,
        agent_id: AgentId,
        project_id: Optional[str],
        environment_ref: Optional[str] = None,
    ) -> tuple[JoySafeterAgent, Optional[str]]:
        """Resolve the agent (and effective environment) a trigger will run.

        Raises if the agent is missing/archived or the environment is
        missing/archived. Returns ``(agent, effective_environment_ref)``.
        """
        return await TriggerRuntimeGate(self.db).resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_ref=environment_ref,
        )

    def _config_for(self, *, type: str, **fields: Any) -> dict[str, Any]:
        return TriggerConfigPolicy.build_config(type=type, **fields)

    def _sync_config(self, trigger: JoySafeterTrigger) -> None:
        TriggerConfigPolicy.sync_config(trigger)

    def _validate_update_candidate(self, trigger: JoySafeterTrigger, fields: dict[str, Any]) -> None:
        """Validate the fully merged trigger state before mutating the ORM row."""
        TriggerConfigPolicy.validate_update_candidate(trigger, fields)

    @staticmethod
    def _trigger_has_active_runs_conflict(
        trigger_id: TriggerId,
        active_tasks: Sequence[JoySafeterTask],
    ) -> ResourceConflictError:
        return ResourceConflictError(
            code="TRIGGER_HAS_ACTIVE_RUNS",
            message="Trigger has active runs. Cancel or wait for them before deleting the trigger.",
            data={
                "trigger_id": str(trigger_id),
                "active_task_ids": [str(task.id) for task in active_tasks],
            },
            user_action="wait_or_cancel",
        )

    @staticmethod
    def _trigger_fire_in_progress_conflict(trigger: JoySafeterTrigger) -> ResourceConflictError:
        return ResourceConflictError(
            code="TRIGGER_FIRE_IN_PROGRESS",
            message="Trigger is currently being fired by the scheduler. Wait for it to finish before deleting.",
            data={
                "trigger_id": str(trigger.id),
                "locked_by": trigger.locked_by,
                "locked_at": trigger.locked_at.isoformat() if trigger.locked_at else None,
            },
            user_action="wait_or_cancel",
        )

    @staticmethod
    def _has_fresh_scheduler_claim(trigger: JoySafeterTrigger, *, lock_grace_sec: int) -> bool:
        if not trigger.locked_by or trigger.locked_at is None:
            return False
        locked_at = trigger.locked_at
        if locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=timezone.utc)
        return locked_at > datetime.now(timezone.utc) - timedelta(seconds=lock_grace_sec)

    async def get(
        self,
        trigger_id: TriggerId,
        project_id: Optional[str] = None,
        *,
        include_deleted: bool = False,
    ) -> Optional[JoySafeterTrigger]:
        conditions = [JoySafeterTrigger.id == trigger_id]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        if not include_deleted:
            conditions.append(JoySafeterTrigger.deleted_at.is_(None))
        result = await self.db.execute(select(JoySafeterTrigger).where(*conditions))
        return result.scalar_one_or_none()

    async def _get_for_update(
        self, trigger_id: TriggerId, project_id: Optional[str] = None
    ) -> Optional[JoySafeterTrigger]:
        result = await self.db.execute(TriggerRuntimeGate.lock_stmt(trigger_id, project_id))
        return result.scalar_one_or_none()

    async def get_claimed_for_fire(
        self,
        trigger_id: TriggerId,
        *,
        expected_locked_by: str,
    ) -> Optional[JoySafeterTrigger]:
        trigger = await self._get_for_update(trigger_id)
        if trigger is None or trigger.locked_by != expected_locked_by:
            return None
        return trigger

    async def get_by_name(
        self,
        name: str,
        project_id: Optional[str],
        *,
        type: Optional[str] = None,
    ) -> Optional[JoySafeterTrigger]:
        conditions = [
            JoySafeterTrigger.name == name,
            JoySafeterTrigger.project_id == project_id,
            JoySafeterTrigger.deleted_at.is_(None),
        ]
        if type is not None:
            conditions.append(JoySafeterTrigger.type == type)
        result = await self.db.execute(select(JoySafeterTrigger).where(*conditions))
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: Optional[str],
        enabled: Optional[bool] = None,
        type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[JoySafeterTrigger]:
        conditions: list[ColumnElement[bool]] = [JoySafeterTrigger.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        if enabled is not None:
            conditions.append(JoySafeterTrigger.enabled == enabled)
        if type is not None:
            conditions.append(JoySafeterTrigger.type == type)
        result = await self.db.execute(
            select(JoySafeterTrigger)
            .where(*conditions)
            .order_by(JoySafeterTrigger.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def delete(self, trigger_id: TriggerId, project_id: Optional[str]) -> bool:
        trigger = await self._get_for_update(trigger_id, project_id=project_id)
        if trigger is None:
            return False
        from app.joysafeter_shared.config.settings import settings

        if self._has_fresh_scheduler_claim(trigger, lock_grace_sec=settings.scheduler_lock_grace_sec):
            raise self._trigger_fire_in_progress_conflict(trigger)
        active_tasks = await self.get_active_tasks(trigger.id)
        if active_tasks:
            raise self._trigger_has_active_runs_conflict(trigger.id, active_tasks)
        now = datetime.now(timezone.utc)
        trigger.deleted_at = now
        trigger.enabled = False
        trigger.next_run_at = None
        trigger.locked_by = None
        trigger.locked_at = None
        trigger.pending_slot_at = None
        trigger.slot_attempts = 0
        self._sync_config(trigger)
        await self.db.commit()
        return True

    def _live_project_filter(self):
        return TriggerRuntimeGate.live_project_filter()

    def _live_agent_filter(self):
        return TriggerRuntimeGate.live_agent_filter()

    def _effective_environment_ref_expr(self):
        return TriggerRuntimeGate.effective_environment_ref_expr()

    def _live_environment_filter(self):
        return TriggerRuntimeGate.live_environment_filter()

    def _claimable_lock_filter(self, stale_before: datetime):
        return TriggerRuntimeGate.claimable_lock_filter(stale_before)

    async def claim_due_cron_triggers(
        self, *, worker_id: str, limit: int, lock_grace_sec: int = 120
    ) -> Sequence[JoySafeterTrigger]:
        """Atomically claim due, enabled cron triggers whose project is live.

        A trigger is claimable when ``next_run_at <= now`` and it is either
        unlocked or its lock is stale (owner crashed). Triggers whose project is
        archived are excluded so an archived project never fires. ``FOR UPDATE
        SKIP LOCKED`` lets concurrent workers grab disjoint batches.
        """
        return await self._scheduler_state().claim_due_cron_triggers(
            worker_id=worker_id,
            limit=limit,
            lock_grace_sec=lock_grace_sec,
        )

    async def release_claim(self, trigger_id: TriggerId, *, expected_locked_by: Optional[str] = None) -> None:
        await self._scheduler_state().release_claim(trigger_id, expected_locked_by=expected_locked_by)

    async def earliest_next_run(self, *, lock_grace_sec: int = 120) -> Optional[datetime]:
        """MIN(next_run_at) across enabled cron triggers with a due slot ahead.

        Lets the scheduler sleep only until the nearest slot (adaptive poll)
        rather than a fixed interval, without busy-looping.
        """
        return await self._scheduler_state().earliest_next_run(lock_grace_sec=lock_grace_sec)

    async def project_triggers_paused(self, project_id: Optional[str]) -> bool:
        """True when the project's server-side trigger kill-switch is enabled."""
        return await TriggerRuntimeGate(self.db).project_triggers_paused(project_id)

    async def project_trigger_block_reason(self, project_id: Optional[str]) -> Optional[str]:
        """Human-readable reason a project should not fire triggers right now."""
        return await TriggerRuntimeGate(self.db).project_trigger_block_reason(project_id)

    async def trigger_runtime_block_reason(self, trigger: JoySafeterTrigger) -> Optional[str]:
        """Human-readable reason this trigger target cannot run right now."""
        return await TriggerRuntimeGate(self.db).trigger_runtime_block_reason(trigger)

    # --- Project / agent lifecycle (cron triggers only) ---

    async def pause_for_project_archive(self, project_id: str) -> None:
        """Pause a project's cron triggers without changing the user's intent.

        The caller owns the transaction. Clears due slots and stale locks so an
        archived project never fires; restore recomputes future slots.
        """
        await self.pause_for_project_triggers(project_id)

    async def pause_for_project_triggers(self, project_id: str) -> None:
        """Clear cron due slots for the project-level trigger kill-switch."""
        result = await self.db.execute(
            select(JoySafeterTrigger).where(
                JoySafeterTrigger.project_id == project_id,
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        for trigger in result.scalars().all():
            trigger.next_run_at = None
            trigger.locked_by = None
            trigger.locked_at = None
            trigger.pending_slot_at = None
            trigger.slot_attempts = 0
            self._sync_config(trigger)

    async def lock_for_agent_lifecycle(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str] = None,
    ) -> builtins.list[JoySafeterTrigger]:
        """Lock every Trigger row before an Agent lifecycle transaction locks Agent.

        Global order: deterministic Trigger IDs, then Agent, then Session/source/
        Credential rows. Scheduler firing already starts with one Trigger row and
        then locks Agent during Snapshot creation, so lifecycle writers must never
        hold Agent while acquiring Trigger locks.
        """
        conditions = [JoySafeterTrigger.agent_id == agent_id]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterTrigger)
            .where(*conditions)
            .order_by(JoySafeterTrigger.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return list(result.scalars().all())

    def pause_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None:
        """Pause live cron Trigger rows already locked by `lock_for_agent_lifecycle`."""
        for trigger in triggers:
            if trigger.type != "cron" or trigger.deleted_at is not None:
                continue
            trigger.next_run_at = None
            trigger.locked_by = None
            trigger.locked_at = None
            trigger.pending_slot_at = None
            trigger.slot_attempts = 0
            self._sync_config(trigger)

    async def pause_for_agent_archive(self, agent_id: AgentId, *, project_id: Optional[str] = None) -> None:
        """Pause cron triggers targeting an archived agent without deleting audit state."""
        await self.pause_for_agent_triggers(agent_id, project_id=project_id)

    async def pause_for_agent_triggers(self, agent_id: AgentId, *, project_id: Optional[str] = None) -> None:
        """Clear cron due slots for an agent that cannot run triggers."""
        triggers = await self.lock_for_agent_lifecycle(agent_id, project_id=project_id)
        self.pause_locked_agent_triggers(triggers)

    async def resume_after_project_restore(self, project_id: str) -> None:
        """Recompute cron trigger fire slots after a project is restored.

        The caller owns the transaction. Enabled cron triggers resume from the
        next future instant; disabled ones stay paused with no due slot.
        """
        await self.resume_after_project_triggers_unpaused(project_id)

    async def resume_after_project_triggers_unpaused(self, project_id: str) -> None:
        """Recompute cron slots only when the project is live and unpaused."""
        project_state = await self.db.execute(
            select(Project.archived_at, Project.triggers_paused).where(Project.id == project_id)
        )
        row = project_state.one_or_none()
        if row is None or row.archived_at is not None or row.triggers_paused:
            return
        result = await self.db.execute(
            select(JoySafeterTrigger).where(
                JoySafeterTrigger.project_id == project_id,
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        for trigger in result.scalars().all():
            trigger.locked_by = None
            trigger.locked_at = None
            trigger.pending_slot_at = None
            trigger.slot_attempts = 0
            trigger.next_run_at = await self._next_run_or_pause(trigger)
            self._sync_config(trigger)

    async def resume_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None:
        """Resume live cron Trigger rows already locked by `lock_for_agent_lifecycle`."""
        for trigger in triggers:
            if trigger.type != "cron" or trigger.deleted_at is not None:
                continue
            trigger.locked_by = None
            trigger.locked_at = None
            trigger.pending_slot_at = None
            trigger.slot_attempts = 0
            trigger.next_run_at = await self._next_run_or_pause(trigger)
            self._sync_config(trigger)

    async def resume_after_agent_restore(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str] = None,
    ) -> None:
        """Recompute cron trigger fire slots after an agent is restored from archive.

        The caller owns the transaction and must clear the agent's ``archived_at``
        before calling this, so ``_next_run_or_pause`` sees the agent as live.
        Enabled cron triggers resume from the next future instant; disabled ones
        (and those whose project/environment is still paused/archived) stay paused
        with no due slot.
        """
        triggers = await self.lock_for_agent_lifecycle(agent_id, project_id=project_id)
        await self.resume_locked_agent_triggers(triggers)

    async def get_active_tasks(self, trigger_id: TriggerId) -> Sequence[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                JoySafeterTask.trigger_id == trigger_id,
                JoySafeterTask.status.in_(_NON_TERMINAL_STATUSES),
            )
        )
        return result.scalars().all()

    async def list_runs(
        self,
        trigger_id: TriggerId,
        *,
        project_id: Optional[str],
        limit: int = 50,
        offset: int = 0,
    ) -> Optional[Sequence[JoySafeterTask]]:
        trigger = await self.get(trigger_id, project_id=project_id, include_deleted=True)
        if trigger is None:
            return None
        result = await self.db.execute(
            select(JoySafeterTask)
            .where(JoySafeterTask.trigger_id == trigger_id)
            .order_by(JoySafeterTask.created_at.desc(), JoySafeterTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_runs_page(
        self,
        trigger_id: TriggerId,
        *,
        project_id: Optional[str],
        limit: int = 50,
        after_id: Optional[TaskId] = None,
    ) -> Optional[tuple[builtins.list[JoySafeterTask], bool]]:
        trigger = await self.get(trigger_id, project_id=project_id, include_deleted=True)
        if trigger is None:
            return None

        query = select(JoySafeterTask).where(JoySafeterTask.trigger_id == trigger_id)
        query = apply_created_at_desc_cursor(query, JoySafeterTask, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        runs = list(result.scalars().all())
        has_more = len(runs) > limit
        return runs[:limit], has_more

    async def advance_after_fire(
        self,
        trigger_id: TriggerId,
        fired_slot: datetime,
        *,
        success: bool = True,
        record_attempt: bool = True,
        task_id: Optional[TaskId] = None,
        session_id: Optional[SessionId] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        expected_locked_by: Optional[str] = None,
    ) -> bool:
        """Release the lock and move ``next_run_at`` to the next FUTURE instant.

        Uses "catch up once and advance": the next fire is computed with
        ``after=now`` (not ``after=fired_slot``), so a trigger that came due
        while the worker was down fires exactly once, then skips the intermediate
        missed slots rather than replaying every one of them. If the target
        became unrunnable while this fire was in flight (project/agent/environment
        archived), ``next_run_at`` is set to NULL so the trigger self-pauses.

        ``record_attempt=False`` advances the slot and releases the lock WITHOUT
        recording a success/failure attempt — used for slots that were
        intentionally skipped (e.g. a FORBID concurrency policy), which are
        neither a success nor a failure.
        """
        return await self._scheduler_state().advance_after_fire(
            trigger_id,
            fired_slot,
            success=success,
            record_attempt=record_attempt,
            task_id=task_id,
            session_id=session_id,
            error=error,
            payload=payload,
            expected_locked_by=expected_locked_by,
        )

    async def record_fire_failure(
        self,
        trigger_id: TriggerId,
        fired_slot: datetime,
        *,
        error: str,
        transient: bool,
        expected_locked_by: Optional[str] = None,
    ) -> bool:
        """Record a failed fire: retry the same slot with backoff, or dead-letter.

        A *transient* failure (fire timeout, admission rate-limit, transient
        service/DB error, half-done REPLACE cancel) keeps the SAME logical slot
        due — ``pending_slot_at`` is retained and ``next_run_at`` is pushed out by
        an exponential backoff — so a later tick re-fires it (with an
        attempt-suffixed idempotency key). After ``scheduler_slot_max_retries``
        transient attempts, or on a *permanent* failure, the slot is abandoned
        (advanced) and one consecutive failure is counted. Once
        ``scheduler_failure_threshold`` consecutive failures accrue the trigger is
        auto-disabled (dead-lettered) so it stops silently failing every slot.

        Returns True if this call dead-lettered (auto-disabled) the trigger.
        """
        return await self._scheduler_state().record_fire_failure(
            trigger_id,
            fired_slot,
            error=error,
            transient=transient,
            expected_locked_by=expected_locked_by,
        )

    async def _next_run_or_pause(self, trigger: JoySafeterTrigger) -> Optional[datetime]:
        """Next future cron instant, or NULL if the trigger should pause.

        Pauses (returns NULL) when disabled, unscheduled, one-off already fired,
        or when the project / agent / environment it targets is paused/archived.
        """
        return await self._scheduler_state().next_run_or_pause(trigger)

    def _apply_attempt(
        self,
        trigger: JoySafeterTrigger,
        *,
        success: Optional[bool],
        task_id: Optional[TaskId] = None,
        session_id: Optional[SessionId] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record attempt bookkeeping on *trigger* in memory (no commit)."""
        TriggerSchedulerStateService.apply_attempt(
            trigger,
            success=success,
            task_id=task_id,
            session_id=session_id,
            error=error,
            payload=payload,
        )

    async def mark_attempt(
        self,
        trigger: JoySafeterTrigger,
        *,
        success: Optional[bool],
        task_id: Optional[TaskId] = None,
        session_id: Optional[SessionId] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        await self._scheduler_state().mark_attempt(
            trigger,
            success=success,
            task_id=task_id,
            session_id=session_id,
            error=error,
            payload=payload,
        )
