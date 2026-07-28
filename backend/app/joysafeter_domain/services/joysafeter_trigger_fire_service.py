from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    payload_filter_matches,
    render_prompt_template,
    render_session_key,
)
from app.joysafeter_domain.services.joysafeter_trigger_runtime_gate import TriggerRuntimeGate
from app.joysafeter_domain.services.joysafeter_trigger_scheduler_state_service import TriggerSchedulerStateService
from app.joysafeter_domain.triggers import get_provider

FireResult = tuple[str, Optional[JoySafeterTask], Optional[uuid.UUID], bool, Optional[str]]
ProjectBlockReason = Callable[[Optional[str]], Awaitable[Optional[str]]]
ResolveRunnableTarget = Callable[..., Awaitable[tuple[JoySafeterAgent, Optional[str]]]]
MarkAttempt = Callable[..., Awaitable[None]]


class TriggerFireService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        project_trigger_block_reason: Optional[ProjectBlockReason] = None,
        resolve_runnable_target: Optional[ResolveRunnableTarget] = None,
        mark_attempt: Optional[MarkAttempt] = None,
    ) -> None:
        self.db = db
        self._runtime_gate = TriggerRuntimeGate(db)
        self._scheduler_state = TriggerSchedulerStateService(db)
        self._project_trigger_block_reason = project_trigger_block_reason
        self._resolve_runnable_target = resolve_runnable_target
        self._mark_attempt = mark_attempt

    async def project_trigger_block_reason(self, project_id: Optional[str]) -> Optional[str]:
        if self._project_trigger_block_reason is not None:
            return await self._project_trigger_block_reason(project_id)
        return await self._runtime_gate.project_trigger_block_reason(project_id)

    async def resolve_runnable_target(
        self,
        *,
        agent_id: uuid.UUID,
        project_id: Optional[str],
        environment_ref: Optional[str] = None,
    ) -> tuple[JoySafeterAgent, Optional[str]]:
        if self._resolve_runnable_target is not None:
            return await self._resolve_runnable_target(
                agent_id=agent_id,
                project_id=project_id,
                environment_ref=environment_ref,
            )
        return await self._runtime_gate.resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_ref=environment_ref,
        )

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

    async def _run_agent_trigger(
        self,
        trigger: JoySafeterTrigger,
        *,
        agent: JoySafeterAgent,
        environment_ref: Optional[str],
        payload: dict[str, Any],
        source: str,
        idempotency_key: str,
        metadata: dict[str, Any],
        enforce_user_quota: bool,
    ) -> FireResult:
        result = await AgentTriggerExecutor(self.db).run(
            AgentTriggerRunConfig(
                agent=agent,
                name=trigger.name,
                source=source,
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
                session_key=render_session_key(trigger.session_key, payload),
                trigger_id=trigger.id,
                metadata=metadata,
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
        agent, environment_ref = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_ref=trigger.environment_ref,
        )
        body_hash = hashlib.sha256(raw_body + auth_fingerprint.encode("utf-8")).hexdigest()
        delivery_key = delivery_id or body_hash
        idempotency_key = get_provider("webhook").idempotency_key(trigger, delivery_key=delivery_key)
        return await self._run_agent_trigger(
            trigger,
            agent=agent,
            environment_ref=environment_ref,
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
        now = now or datetime.now(timezone.utc)
        provider = get_provider("manual")
        payload = provider.build_payload(trigger, now=now)
        block_reason = await self.project_trigger_block_reason(trigger.project_id)
        if block_reason is not None:
            await self.mark_attempt(trigger, success=None, payload=payload)
            return "skipped", None, None, False, block_reason
        agent, environment_ref = await self.resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_ref=trigger.environment_ref,
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
            environment_ref=environment_ref,
            payload=payload,
            source=f"trigger:manual:{trigger.id}",
            idempotency_key=idempotency_key,
            metadata={"trigger_id": str(trigger.id), "trigger_type": "manual", "source_trigger_type": trigger.type},
            enforce_user_quota=True,
        )
