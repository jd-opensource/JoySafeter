from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    AgentTriggerRunResult,
    payload_filter_matches,
    render_prompt_template,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_domain.triggers import get_provider
from app.joysafeter_shared.common.app_errors import (
    NotFoundError,
    RequestValidationAppError,
    ResourceConflictError,
)
from app.joysafeter_shared.utils.cron import compute_next_run

_NON_TERMINAL_STATUSES = [s.value for s in JoySafeterTaskStatus if s not in JOYSAFETER_TERMINAL_STATUSES]


class JoySafeterTriggerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_runnable_target(
        self,
        *,
        agent_id: uuid.UUID,
        project_id: Optional[str],
        environment_ref: Optional[str] = None,
    ) -> tuple[JoySafeterAgent, Optional[str]]:
        """Resolve the agent (and effective environment) a trigger will run.

        Raises if the agent is missing/archived or the environment is
        missing/archived. Returns ``(agent, effective_environment_ref)``.
        """
        conditions = [JoySafeterAgent.id == agent_id, JoySafeterAgent.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(*conditions))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundError(
                code="TRIGGER_AGENT_NOT_FOUND",
                message="Agent not found",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )
        if agent.archived_at is not None:
            raise ResourceConflictError(
                code="AGENT_ARCHIVED",
                message="Agent is archived and cannot create new triggered runs.",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )

        effective_environment_ref = environment_ref or agent.environment_ref
        if effective_environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                effective_environment_ref,
                project_id=project_id,
            )
            if env is None:
                raise RequestValidationAppError(
                    code="TRIGGER_ENVIRONMENT_NOT_FOUND",
                    message=f"Environment not found: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref},
                    user_action="fix_input",
                )
            if env.archived_at is not None:
                raise ResourceConflictError(
                    code="ENVIRONMENT_ARCHIVED",
                    message=f"Environment is archived: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref, "environment_id": str(env.id)},
                    user_action="refresh",
                )
        return agent, effective_environment_ref

    def _config_for(self, *, type: str, **fields: Any) -> dict[str, Any]:
        return get_provider(type).build_config(**fields)

    def _sync_config(self, trigger: JoySafeterTrigger) -> None:
        trigger.config = self._config_for(
            type=trigger.type,
            cron_expr=trigger.cron_expr,
            timezone=trigger.timezone or "UTC",
            concurrency_policy=trigger.concurrency_policy,
            next_run_at=trigger.next_run_at.isoformat() if trigger.next_run_at else None,
            last_fired_slot=trigger.last_fired_slot.isoformat() if trigger.last_fired_slot else None,
            secret_ref=trigger.secret_ref,
            secret_key=trigger.secret_key or "WEBHOOK_SECRET",
            auth_methods=(trigger.config or {}).get("auth_methods"),
            dedupe_header=(trigger.config or {}).get("dedupe_header"),
        )

    async def _notify_scheduler(self, trigger: JoySafeterTrigger) -> None:
        """Wake the scheduler loop immediately via Postgres NOTIFY (best-effort).

        Only meaningful for an enabled cron trigger with a due slot ahead; the
        poll loop remains the correctness backstop, so any NOTIFY failure is
        swallowed rather than surfaced to the caller.
        """
        from app.joysafeter_shared.config.settings import settings

        if not settings.scheduler_notify_enabled:
            return
        if trigger.type != "cron" or not trigger.enabled or trigger.next_run_at is None:
            return
        try:
            await self.db.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": settings.scheduler_notify_channel, "payload": str(trigger.id)},
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()

    async def _resolve_webhook_secret(self, trigger: JoySafeterTrigger) -> str:
        if not trigger.secret_ref:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_REF_REQUIRED",
                message="Webhook trigger requires secret_ref",
                data={"trigger_id": str(trigger.id)},
                user_action="fix_input",
            )
        secret_svc = SecretService(self.db)
        secret = await secret_svc.get_secret_by_name(trigger.secret_ref, project_id=trigger.project_id)
        if secret is None:
            raise NotFoundError(
                code="TRIGGER_SECRET_NOT_FOUND",
                message=f"Secret not found: {trigger.secret_ref}",
                data={"secret_ref": trigger.secret_ref, "trigger_id": str(trigger.id)},
                user_action="fix_input",
            )
        secret_data = secret_svc.get_secret_data(secret)
        secret_key = trigger.secret_key or "WEBHOOK_SECRET"
        value = secret_data.get(secret_key)
        if not value:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_KEY_NOT_FOUND",
                message=f"Secret key not found: {secret_key}",
                data={"secret_ref": trigger.secret_ref, "secret_key": secret_key},
                user_action="fix_input",
            )
        return value

    async def create(
        self,
        *,
        name: str,
        agent_id: uuid.UUID,
        prompt_template: str,
        type: str = "webhook",
        system_prompt: Optional[str] = None,
        environment_ref: Optional[str] = None,
        description: Optional[str] = None,
        enabled: bool = True,
        session_mode: str = "fresh",
        pinned_session_id: Optional[uuid.UUID] = None,
        session_key: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
        cron_expr: Optional[str] = None,
        timezone: str = "UTC",
        run_at: Optional[datetime] = None,
        concurrency_policy: str = "allow",
        secret_ref: Optional[str] = None,
        secret_key: Optional[str] = "WEBHOOK_SECRET",
        auth_methods: Optional[list[str]] = None,
        dedupe_header: Optional[str] = "x-joysafeter-delivery",
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> JoySafeterTrigger:
        await self.resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_ref=environment_ref,
        )
        if type == "webhook" and secret_ref:
            secret = await SecretService(self.db).get_secret_by_name(secret_ref, project_id=project_id)
            if secret is None:
                raise NotFoundError(
                    code="TRIGGER_SECRET_NOT_FOUND",
                    message=f"Secret not found: {secret_ref}",
                    data={"secret_ref": secret_ref},
                    user_action="fix_input",
                )
        # A cron-type trigger is recurring (cron_expr) or one-off (run_at); the
        # one-off's next_run_at is the instant itself, and it parks after firing
        # because _next_run_or_pause returns None when there is no cron_expr.
        if type == "cron" and cron_expr:
            next_run_at = compute_next_run(cron_expr, timezone)
        elif type == "cron" and run_at is not None:
            next_run_at = run_at
        else:
            next_run_at = None
        trigger = JoySafeterTrigger(
            name=name,
            type=type,
            agent_id=agent_id,
            prompt_template=prompt_template,
            system_prompt=system_prompt,
            environment_ref=environment_ref,
            description=description,
            enabled=enabled,
            session_mode=session_mode,
            pinned_session_id=pinned_session_id,
            session_key=session_key,
            filter=filter or {},
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            cron_expr=cron_expr,
            timezone=timezone if type == "cron" else None,
            run_at=run_at if type == "cron" else None,
            concurrency_policy=concurrency_policy,
            next_run_at=next_run_at,
            secret_ref=secret_ref,
            secret_key=secret_key,
            config=self._config_for(
                type=type,
                cron_expr=cron_expr,
                timezone=timezone,
                concurrency_policy=concurrency_policy,
                next_run_at=next_run_at.isoformat() if next_run_at else None,
                secret_ref=secret_ref,
                secret_key=secret_key,
                auth_methods=auth_methods,
                dedupe_header=dedupe_header,
            ),
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
        )
        self.db.add(trigger)
        await self.db.commit()
        await self.db.refresh(trigger)
        await self._notify_scheduler(trigger)
        return trigger

    async def get(self, trigger_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterTrigger]:
        conditions = [JoySafeterTrigger.id == trigger_id]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        result = await self.db.execute(select(JoySafeterTrigger).where(*conditions))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, project_id: Optional[str]) -> Optional[JoySafeterTrigger]:
        result = await self.db.execute(
            select(JoySafeterTrigger).where(JoySafeterTrigger.name == name, JoySafeterTrigger.project_id == project_id)
        )
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
        conditions = []
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        if enabled is not None:
            conditions.append(JoySafeterTrigger.enabled == enabled)
        if type is not None:
            conditions.append(JoySafeterTrigger.type == type)
        result = await self.db.execute(
            select(JoySafeterTrigger).where(*conditions).order_by(JoySafeterTrigger.created_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def update(self, trigger_id: uuid.UUID, project_id: Optional[str], **fields: Any) -> Optional[JoySafeterTrigger]:
        trigger = await self.get(trigger_id, project_id=project_id)
        if trigger is None:
            return None
        next_environment_ref = fields["environment_ref"] if "environment_ref" in fields else trigger.environment_ref
        if "environment_ref" in fields or fields.get("enabled") is True:
            await self.resolve_runnable_target(
                agent_id=trigger.agent_id,
                project_id=trigger.project_id,
                environment_ref=next_environment_ref,
            )
        if trigger.type == "webhook" and "secret_ref" in fields:
            secret = await SecretService(self.db).get_secret_by_name(fields["secret_ref"], project_id=trigger.project_id)
            if secret is None:
                raise NotFoundError(
                    code="TRIGGER_SECRET_NOT_FOUND",
                    message=f"Secret not found: {fields['secret_ref']}",
                    data={"secret_ref": fields["secret_ref"]},
                    user_action="fix_input",
                )
        recompute_next = trigger.type == "cron" and any(k in fields for k in ("cron_expr", "timezone", "run_at"))
        for key, value in fields.items():
            if key in {"auth_methods", "dedupe_header"}:
                config = dict(trigger.config or {})
                config[key] = value
                trigger.config = config
            elif hasattr(trigger, key):
                setattr(trigger, key, value)
        if recompute_next:
            if trigger.cron_expr:
                trigger.next_run_at = compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")
            elif trigger.run_at is not None and trigger.last_fired_slot is None:
                # A not-yet-fired one-off: re-arm to its instant.
                trigger.next_run_at = trigger.run_at
        if fields.get("enabled") is True:
            # Re-enabling clears any auto-disable (dead-letter) and in-progress
            # retry state, and resumes the schedule from the next future slot so a
            # trigger disabled at consecutive_failures==threshold starts clean.
            trigger.consecutive_failures = 0
            trigger.auto_disabled_at = None
            trigger.disabled_reason = None
            trigger.slot_attempts = 0
            trigger.pending_slot_at = None
            if trigger.type == "cron" and trigger.next_run_at is None:
                if trigger.cron_expr:
                    trigger.next_run_at = compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")
                elif trigger.run_at is not None and trigger.last_fired_slot is None:
                    trigger.next_run_at = trigger.run_at
        self._sync_config(trigger)
        await self.db.commit()
        await self.db.refresh(trigger)
        await self._notify_scheduler(trigger)
        return trigger

    async def delete(self, trigger_id: uuid.UUID, project_id: Optional[str]) -> bool:
        trigger = await self.get(trigger_id, project_id=project_id)
        if trigger is None:
            return False
        await self.db.delete(trigger)
        await self.db.commit()
        return True

    async def claim_due_cron_triggers(self, *, worker_id: str, limit: int, lock_grace_sec: int = 120) -> Sequence[JoySafeterTrigger]:
        """Atomically claim due, enabled cron triggers whose project is live.

        A trigger is claimable when ``next_run_at <= now`` and it is either
        unlocked or its lock is stale (owner crashed). Triggers whose project is
        archived are excluded so an archived project never fires. ``FOR UPDATE
        SKIP LOCKED`` lets concurrent workers grab disjoint batches.
        """
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=lock_grace_sec)
        stmt = (
            select(JoySafeterTrigger)
            .where(
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.enabled.is_(True),
                JoySafeterTrigger.next_run_at.is_not(None),
                JoySafeterTrigger.next_run_at <= now,
                or_(JoySafeterTrigger.locked_at.is_(None), JoySafeterTrigger.locked_at < stale_before),
                or_(
                    JoySafeterTrigger.project_id.is_(None),
                    select(Project.id)
                    .where(
                        Project.id == JoySafeterTrigger.project_id,
                        Project.archived_at.is_(None),
                    )
                    .exists(),
                ),
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

    async def release_claim(self, trigger_id: uuid.UUID) -> None:
        await self.db.execute(
            update(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id).values(locked_by=None, locked_at=None)
        )
        await self.db.commit()

    async def earliest_next_run(self) -> Optional[datetime]:
        """MIN(next_run_at) across enabled cron triggers with a due slot ahead.

        Lets the scheduler sleep only until the nearest slot (adaptive poll)
        rather than a fixed interval, without busy-looping.
        """
        result = await self.db.execute(
            select(func.min(JoySafeterTrigger.next_run_at)).where(
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.enabled.is_(True),
                JoySafeterTrigger.next_run_at.is_not(None),
            )
        )
        return result.scalar_one_or_none()

    # --- Project / agent lifecycle (cron triggers only) ---

    async def pause_for_project_archive(self, project_id: str) -> None:
        """Pause a project's cron triggers without changing the user's intent.

        The caller owns the transaction. Clears due slots and stale locks so an
        archived project never fires; restore recomputes future slots.
        """
        await self.db.execute(
            update(JoySafeterTrigger)
            .where(JoySafeterTrigger.project_id == project_id, JoySafeterTrigger.type == "cron")
            .values(next_run_at=None, locked_by=None, locked_at=None)
        )

    async def pause_for_agent_archive(self, agent_id: uuid.UUID) -> None:
        """Pause cron triggers targeting an archived agent without deleting audit state."""
        await self.db.execute(
            update(JoySafeterTrigger)
            .where(JoySafeterTrigger.agent_id == agent_id, JoySafeterTrigger.type == "cron")
            .values(next_run_at=None, locked_by=None, locked_at=None)
        )

    async def resume_after_project_restore(self, project_id: str) -> None:
        """Recompute cron trigger fire slots after a project is restored.

        The caller owns the transaction. Enabled cron triggers resume from the
        next future instant; disabled ones stay paused with no due slot.
        """
        result = await self.db.execute(
            select(JoySafeterTrigger).where(
                JoySafeterTrigger.project_id == project_id, JoySafeterTrigger.type == "cron"
            )
        )
        for trigger in result.scalars().all():
            trigger.locked_by = None
            trigger.locked_at = None
            if trigger.enabled and trigger.cron_expr:
                trigger.next_run_at = compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")
            else:
                trigger.next_run_at = None
            self._sync_config(trigger)

    async def get_active_tasks(self, trigger_id: uuid.UUID) -> Sequence[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                JoySafeterTask.trigger_id == trigger_id,
                JoySafeterTask.status.in_(_NON_TERMINAL_STATUSES),
            )
        )
        return result.scalars().all()

    async def list_runs(
        self,
        trigger_id: uuid.UUID,
        *,
        project_id: Optional[str],
        limit: int = 50,
        offset: int = 0,
    ) -> Optional[Sequence[JoySafeterTask]]:
        trigger = await self.get(trigger_id, project_id=project_id)
        if trigger is None:
            return None
        result = await self.db.execute(
            select(JoySafeterTask)
            .where(JoySafeterTask.trigger_id == trigger_id)
            .order_by(JoySafeterTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

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
    ) -> None:
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
        trigger = await self.get(trigger_id)
        if trigger is None:
            return
        trigger.last_fired_slot = fired_slot
        trigger.locked_by = None
        trigger.locked_at = None
        # The slot is done (fired / deduped / intentionally skipped): clear any
        # in-progress retry state so the next slot starts clean.
        trigger.slot_attempts = 0
        trigger.pending_slot_at = None
        if record_attempt:
            self._apply_attempt(trigger, success=success, task_id=task_id, session_id=session_id, error=error, payload=payload)
        trigger.next_run_at = await self._next_run_or_pause(trigger)
        self._sync_config(trigger)
        await self.db.commit()

    async def record_fire_failure(
        self,
        trigger_id: uuid.UUID,
        fired_slot: datetime,
        *,
        error: str,
        transient: bool,
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
        from app.joysafeter_shared.config.settings import settings

        trigger = await self.get(trigger_id)
        if trigger is None:
            return False
        now = datetime.now(timezone.utc)
        trigger.slot_attempts = (trigger.slot_attempts or 0) + 1
        trigger.pending_slot_at = fired_slot
        trigger.last_attempt_at = now
        trigger.last_error = error
        trigger.locked_by = None
        trigger.locked_at = None

        if transient and trigger.slot_attempts <= settings.scheduler_slot_max_retries:
            backoff = min(
                settings.scheduler_retry_backoff_cap_sec,
                settings.scheduler_retry_backoff_base_sec * (2 ** (trigger.slot_attempts - 1)),
            )
            trigger.next_run_at = now + timedelta(seconds=backoff)
            self._sync_config(trigger)
            await self.db.commit()
            return False

        # Permanent, or transient retries exhausted: abandon the slot and count a
        # consecutive failure. Dead-letter (auto-disable) at the threshold.
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
            trigger.next_run_at = await self._next_run_or_pause(trigger)
        self._sync_config(trigger)
        await self.db.commit()
        return dead_lettered

    async def _next_run_or_pause(self, trigger: JoySafeterTrigger) -> Optional[datetime]:
        """Next future cron instant, or NULL if the trigger should pause.

        Pauses (returns NULL) when disabled, non-cron, or when the project /
        agent / environment it targets is archived.
        """
        if not trigger.enabled or not trigger.cron_expr:
            return None
        if trigger.project_id is not None:
            archived = await self.db.execute(
                select(Project.archived_at).where(Project.id == trigger.project_id)
            )
            if archived.scalar_one_or_none() is not None:
                return None
        agent_row = (
            await self.db.execute(
                select(JoySafeterAgent.archived_at, JoySafeterAgent.environment_ref).where(
                    JoySafeterAgent.id == trigger.agent_id
                )
            )
        ).one_or_none()
        if agent_row is None or agent_row.archived_at is not None:
            return None
        environment_ref = trigger.environment_ref or agent_row.environment_ref
        if environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                environment_ref,
                project_id=trigger.project_id,
            )
            if env is None or env.archived_at is not None:
                return None
        return compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")

    def _apply_attempt(
        self,
        trigger: JoySafeterTrigger,
        *,
        success: bool,
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record attempt bookkeeping on *trigger* in memory (no commit)."""
        trigger.last_attempt_at = datetime.now(timezone.utc)
        if task_id is not None:
            trigger.last_task_id = task_id
        if session_id is not None:
            trigger.last_session_id = session_id
            if trigger.session_mode == "reuse":
                trigger.reusable_session_id = session_id
        if payload is not None:
            trigger.last_payload = payload
        if success:
            trigger.last_success_at = trigger.last_attempt_at
            trigger.last_error = None
            trigger.consecutive_failures = 0
        else:
            trigger.last_error = error or "trigger fire failed"
            trigger.consecutive_failures = (trigger.consecutive_failures or 0) + 1

    async def mark_attempt(
        self,
        trigger: JoySafeterTrigger,
        *,
        success: bool,
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self._apply_attempt(trigger, success=success, task_id=task_id, session_id=session_id, error=error, payload=payload)
        self._sync_config(trigger)
        await self.db.commit()

    @staticmethod
    def verify_signature(raw_body: bytes, secret: str, signature_header: Optional[str]) -> bool:
        if not signature_header:
            return False
        signature = signature_header.strip()
        if signature.startswith("sha256="):
            signature = signature.removeprefix("sha256=")
        if len(signature) != 64:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.lower(), expected.lower())

    @staticmethod
    def verify_token(secret: str, token: Optional[str]) -> bool:
        return bool(token) and hmac.compare_digest(token or "", secret)

    async def verify_webhook_auth(self, trigger: JoySafeterTrigger, raw_body: bytes, signature: Optional[str], token: Optional[str]) -> bool:
        secret = await self._resolve_webhook_secret(trigger)
        methods = set((trigger.config or {}).get("auth_methods") or ["hmac", "bearer", "token"])
        if "hmac" in methods and self.verify_signature(raw_body, secret, signature):
            return True
        if ({"bearer", "token"} & methods) and self.verify_token(secret, token):
            return True
        return False

    async def fire_webhook(
        self,
        trigger: JoySafeterTrigger,
        *,
        raw_body: bytes,
        payload: dict[str, Any],
        delivery_id: Optional[str],
        auth_fingerprint: str,
        ignore_enabled: bool = False,
    ) -> tuple[str, Optional[JoySafeterTask], Optional[uuid.UUID], bool, Optional[str]]:
        if not trigger.enabled and not ignore_enabled:
            return "skipped", None, None, False, "trigger disabled"
        if trigger.type != "webhook":
            return "skipped", None, None, False, "trigger is not webhook"
        if not payload_filter_matches(trigger.filter, payload):
            await self.mark_attempt(trigger, success=True, payload=payload)
            return "skipped", None, None, False, "delivery did not match filter"
        agent, environment_ref = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_ref=trigger.environment_ref,
        )
        body_hash = hashlib.sha256(raw_body + auth_fingerprint.encode("utf-8")).hexdigest()
        delivery_key = delivery_id or body_hash
        idempotency_key = get_provider("webhook").idempotency_key(trigger, delivery_key=delivery_key)
        rendered_prompt = render_prompt_template(trigger.prompt_template, payload)
        rendered_key = render_prompt_template(trigger.session_key, payload) if trigger.session_key else None
        result = await AgentTriggerExecutor(self.db).run(
            AgentTriggerRunConfig(
                agent=agent,
                name=trigger.name,
                source=f"trigger:webhook:{trigger.id}",
                prompt=rendered_prompt,
                system_prompt=trigger.system_prompt,
                environment_ref=environment_ref,
                timeout_sec=trigger.timeout_sec,
                max_retries=trigger.max_retries,
                project_id=trigger.project_id,
                user_id=trigger.user_id,
                org_id=trigger.org_id,
                idempotency_key=idempotency_key,
                session_mode=trigger.session_mode,
                pinned_session_id=trigger.pinned_session_id,
                reusable_session_id=trigger.reusable_session_id,
                session_key=rendered_key,
                trigger_id=trigger.id,
                metadata={"trigger_id": str(trigger.id), "trigger_type": "webhook"},
            ),
            # A webhook fire is a service principal (external caller, not a signed-in
            # human), so — like cron — it is bounded by the project quota only, not
            # the per-user quota. Keeps service-principal quota policy consistent.
            enforce_user_quota=False,
        )
        await self.mark_attempt(trigger, success=True, task_id=result.task.id, session_id=result.session.id, payload=payload)
        return ("fired" if result.created else "deduped"), result.task, result.session.id, not result.created, None

    async def fire_manual(
        self,
        trigger: JoySafeterTrigger,
        *,
        idempotency_header: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> AgentTriggerRunResult:
        """Fire a trigger on demand (the "Run now" action).

        Mirrors ``fire_webhook`` for the human-initiated path: a signed-in user
        clicked the button, so this enforces the per-user quota (unlike the
        service-principal cron/webhook paths) and does not gate on ``enabled``.
        Without an explicit ``Idempotency-Key`` the provider collapses accidental
        double-clicks in a short window into one fire.
        """
        now = now or datetime.now(timezone.utc)
        agent, environment_ref = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_ref=trigger.environment_ref,
        )
        provider = get_provider("manual")
        payload = provider.build_payload(trigger, now=now)
        idempotency_key = provider.idempotency_key(
            trigger,
            idempotency_header=idempotency_header,
            user_id=trigger.user_id,
            now=now,
        )
        result = await AgentTriggerExecutor(self.db).run(
            AgentTriggerRunConfig(
                agent=agent,
                name=trigger.name,
                source=f"trigger:manual:{trigger.id}",
                prompt=render_prompt_template(trigger.prompt_template, payload),
                system_prompt=trigger.system_prompt,
                environment_ref=environment_ref,
                timeout_sec=trigger.timeout_sec,
                max_retries=trigger.max_retries,
                project_id=trigger.project_id,
                user_id=trigger.user_id,
                org_id=trigger.org_id,
                idempotency_key=idempotency_key,
                session_mode=trigger.session_mode,
                pinned_session_id=trigger.pinned_session_id,
                reusable_session_id=trigger.reusable_session_id,
                session_key=render_prompt_template(trigger.session_key, payload) if trigger.session_key else None,
                trigger_id=trigger.id,
                metadata={"trigger_id": str(trigger.id), "trigger_type": "manual", "source_trigger_type": trigger.type},
            ),
            enforce_user_quota=True,
        )
        await self.mark_attempt(
            trigger,
            success=True,
            task_id=result.task.id,
            session_id=result.session.id,
            payload=payload,
        )
        return result

    async def build_webhook_curl(self, trigger: JoySafeterTrigger, *, url: str, sample_body: Optional[dict[str, Any]] = None) -> str:
        """A copy-paste ``curl`` that delivers a correctly HMAC-signed sample body.

        The trigger owner already holds the secret, so returning a signature
        computed for the sample body is a debugging convenience, not a leak.
        """
        import json as _json

        secret = await self._resolve_webhook_secret(trigger)
        body = _json.dumps(sample_body if sample_body is not None else {"example": "payload"}, separators=(",", ":"))
        signature = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        return (
            f"curl -X POST '{url}' "
            f"-H 'Content-Type: application/json' "
            f"-H 'X-JoySafeter-Signature: sha256={signature}' "
            f"-d '{body}'"
        )
