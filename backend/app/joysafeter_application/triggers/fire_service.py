from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.triggers.execution_service import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    payload_filter_matches,
    render_prompt_template,
    render_session_key,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_runtime_gate import TriggerRuntimeGate
from app.joysafeter_domain.services.joysafeter_trigger_scheduler_state_service import TriggerSchedulerStateService
from app.joysafeter_domain.triggers import get_provider
from app.joysafeter_shared.ids import AgentId, EnvironmentId, ProjectId, SessionId, TaskId

FireResult = tuple[str, Optional[JoySafeterTask], Optional[SessionId], bool, Optional[str]]
ProjectBlockReason = Callable[[ProjectId | None], Awaitable[Optional[str]]]
ResolveRunnableTarget = Callable[..., Awaitable[tuple[JoySafeterAgent, Optional[EnvironmentId]]]]
MarkAttempt = Callable[..., Awaitable[None]]


class TriggerFireService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        project_trigger_block_reason: Optional[ProjectBlockReason] = None,
        resolve_runnable_target: Optional[ResolveRunnableTarget] = None,
        mark_attempt: Optional[MarkAttempt] = None,
        audit_actor: CredentialAuditActor,
    ) -> None:
        self.db = db
        self._runtime_gate = TriggerRuntimeGate(db)
        self._scheduler_state = TriggerSchedulerStateService(db)
        self._project_trigger_block_reason = project_trigger_block_reason
        self._resolve_runnable_target = resolve_runnable_target
        self._mark_attempt = mark_attempt
        self._audit_actor = audit_actor

    async def project_trigger_block_reason(self, project_id: ProjectId | None) -> Optional[str]:
        if self._project_trigger_block_reason is not None:
            return await self._project_trigger_block_reason(project_id)
        return await self._runtime_gate.project_trigger_block_reason(project_id)

    async def resolve_runnable_target(
        self,
        *,
        agent_id: AgentId,
        project_id: ProjectId | None,
        environment_id: Optional[EnvironmentId] = None,
    ) -> tuple[JoySafeterAgent, Optional[EnvironmentId]]:
        if self._resolve_runnable_target is not None:
            return await self._resolve_runnable_target(
                agent_id=agent_id,
                project_id=project_id,
                environment_id=environment_id,
            )
        return await self._runtime_gate.resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_id=environment_id,
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
        if self._mark_attempt is not None:
            await self._mark_attempt(
                trigger,
                success=success,
                task_id=task_id,
                session_id=session_id,
                error=error,
                payload=payload,
            )
            return
        await self._scheduler_state.mark_attempt(
            trigger,
            success=success,
            task_id=task_id,
            session_id=session_id,
            error=error,
            payload=payload,
        )

    async def _lock_trigger_for_fire(self, trigger: JoySafeterTrigger) -> JoySafeterTrigger:
        project_id = getattr(trigger, "project_id", None)
        result = await self.db.execute(TriggerRuntimeGate.lock_stmt(trigger.id, project_id))
        locked: Optional[JoySafeterTrigger] = result.scalar_one_or_none()
        if locked is None:
            raise TriggerRuntimeGate.trigger_not_found_error(trigger.id)
        return locked

    async def _run_agent_trigger(
        self,
        trigger: JoySafeterTrigger,
        *,
        agent: JoySafeterAgent,
        environment_id: Optional[EnvironmentId],
        payload: dict[str, Any],
        source: str,
        idempotency_key: str,
        metadata: dict[str, Any],
        enforce_user_quota: bool,
    ) -> FireResult:
        result = await AgentTriggerExecutor(self.db, audit_actor=self._audit_actor).run(
            AgentTriggerRunConfig(
                agent=agent,
                name=trigger.name,
                source=source,
                prompt=render_prompt_template(trigger.prompt_template, payload),
                environment_id=environment_id,
                timeout_sec=trigger.timeout_sec,
                max_retries=trigger.max_retries,
                project_id=trigger.project_id,
                user_id=trigger.user_id,
                org_id=trigger.org_id,
                idempotency_key=idempotency_key,
                session_mode=trigger.session_mode,
                pinned_session_id=trigger.pinned_session_id,
                reusable_session_id=trigger.reusable_session_id,
                session_key=render_session_key(trigger.session_key, payload),
                trigger_id=trigger.id,
                metadata=metadata,
                system_prompt=getattr(trigger, "system_prompt", None),
            ),
            enforce_user_quota=enforce_user_quota,
        )
        await self.mark_attempt(
            trigger,
            success=True,
            task_id=result.task.id,
            session_id=result.session.id,
            payload=payload,
        )
        return ("fired" if result.created else "deduped"), result.task, result.session.id, not result.created, None

    async def fire_webhook(
        self,
        trigger: JoySafeterTrigger,
        *,
        raw_body: bytes,
        payload: dict[str, Any],
        delivery_id: Optional[str],
        auth_fingerprint: str,
        ignore_enabled: bool = False,
    ) -> FireResult:
        trigger = await self._lock_trigger_for_fire(trigger)
        if not trigger.enabled and not ignore_enabled:
            return "skipped", None, None, False, "trigger disabled"
        if trigger.type != "webhook":
            return "skipped", None, None, False, "trigger is not webhook"
        block_reason = await self.project_trigger_block_reason(trigger.project_id)
        if block_reason is not None:
            await self.mark_attempt(trigger, success=None, payload=payload)
            return "skipped", None, None, False, block_reason
        if not payload_filter_matches(trigger.filter, payload):
            await self.mark_attempt(trigger, success=None, payload=payload)
            return "skipped", None, None, False, "delivery did not match filter"
        agent, environment_id = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_id=trigger.environment_id,
        )
        body_hash = hashlib.sha256(raw_body + auth_fingerprint.encode("utf-8")).hexdigest()
        delivery_key = delivery_id or body_hash
        idempotency_key = get_provider("webhook").idempotency_key(trigger, delivery_key=delivery_key)
        return await self._run_agent_trigger(
            trigger,
            agent=agent,
            environment_id=environment_id,
            payload=payload,
            source=f"trigger:webhook:{trigger.id}",
            idempotency_key=idempotency_key,
            metadata={"trigger_id": str(trigger.id), "trigger_type": "webhook"},
            enforce_user_quota=False,
        )

    async def fire_manual(
        self,
        trigger: JoySafeterTrigger,
        *,
        idempotency_header: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> FireResult:
        trigger = await self._lock_trigger_for_fire(trigger)
        now = now or datetime.now(timezone.utc)
        provider = get_provider("manual")
        payload = provider.build_payload(trigger, now=now)
        block_reason = await self.project_trigger_block_reason(trigger.project_id)
        if block_reason is not None:
            await self.mark_attempt(trigger, success=None, payload=payload)
            return "skipped", None, None, False, block_reason
        agent, environment_id = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_id=trigger.environment_id,
        )
        idempotency_key = provider.idempotency_key(
            trigger,
            idempotency_header=idempotency_header,
            user_id=trigger.user_id,
            now=now,
        )
        return await self._run_agent_trigger(
            trigger,
            agent=agent,
            environment_id=environment_id,
            payload=payload,
            source=f"trigger:manual:{trigger.id}",
            idempotency_key=idempotency_key,
            metadata={"trigger_id": str(trigger.id), "trigger_type": "manual", "source_trigger_type": trigger.type},
            enforce_user_quota=True,
        )
