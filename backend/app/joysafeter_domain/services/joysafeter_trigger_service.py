from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.agent_trigger_execution import (
    AgentTriggerExecutor,
    AgentTriggerRunConfig,
    payload_filter_matches,
    render_prompt_template,
)
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError
from app.joysafeter_shared.utils.cron import compute_next_run

_NON_TERMINAL_STATUSES = [s.value for s in JoySafeterTaskStatus if s not in JOYSAFETER_TERMINAL_STATUSES]


class JoySafeterTriggerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _config_for(self, *, type: str, **fields: Any) -> dict[str, Any]:
        if type == "cron":
            return {
                "cron_expr": fields.get("cron_expr"),
                "timezone": fields.get("timezone") or "UTC",
                "concurrency_policy": fields.get("concurrency_policy") or "allow",
                "next_run_at": fields.get("next_run_at"),
                "last_fired_slot": fields.get("last_fired_slot"),
            }
        if type == "webhook":
            return {
                "secret_ref": fields.get("secret_ref"),
                "secret_key": fields.get("secret_key") or "WEBHOOK_SECRET",
                "auth_methods": fields.get("auth_methods") or ["hmac", "bearer", "token"],
                "dedupe_header": fields.get("dedupe_header") or "x-joysafeter-delivery",
            }
        return {}

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
        filter: Optional[dict[str, Any]] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
        cron_expr: Optional[str] = None,
        timezone: str = "UTC",
        concurrency_policy: str = "allow",
        secret_ref: Optional[str] = None,
        secret_key: Optional[str] = "WEBHOOK_SECRET",
        auth_methods: Optional[list[str]] = None,
        dedupe_header: Optional[str] = "x-joysafeter-delivery",
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> JoySafeterTrigger:
        await JoySafeterScheduleService(self.db).resolve_runnable_target(
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
        next_run_at = compute_next_run(cron_expr, timezone) if type == "cron" and cron_expr else None
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
            filter=filter or {},
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            cron_expr=cron_expr,
            timezone=timezone if type == "cron" else None,
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
            await JoySafeterScheduleService(self.db).resolve_runnable_target(
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
        recompute_next = trigger.type == "cron" and any(k in fields for k in ("cron_expr", "timezone"))
        for key, value in fields.items():
            if key in {"auth_methods", "dedupe_header"}:
                config = dict(trigger.config or {})
                config[key] = value
                trigger.config = config
            elif hasattr(trigger, key):
                setattr(trigger, key, value)
        if recompute_next and trigger.cron_expr:
            trigger.next_run_at = compute_next_run(trigger.cron_expr, trigger.timezone or "UTC")
        self._sync_config(trigger)
        await self.db.commit()
        await self.db.refresh(trigger)
        return trigger

    async def delete(self, trigger_id: uuid.UUID, project_id: Optional[str]) -> bool:
        trigger = await self.get(trigger_id, project_id=project_id)
        if trigger is None:
            return False
        await self.db.delete(trigger)
        await self.db.commit()
        return True

    async def claim_due_cron_triggers(self, *, worker_id: str, limit: int, lock_grace_sec: int = 120) -> Sequence[JoySafeterTrigger]:
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
        for trigger in triggers:
            await self.db.refresh(trigger)
        return triggers

    async def release_claim(self, trigger_id: uuid.UUID) -> None:
        await self.db.execute(
            update(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_id).values(locked_by=None, locked_at=None)
        )
        await self.db.commit()

    async def get_active_tasks(self, trigger_id: uuid.UUID) -> Sequence[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                JoySafeterTask.schedule_id == trigger_id,
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
            .where(JoySafeterTask.schedule_id == trigger_id)
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
        task_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        error: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        trigger = await self.get(trigger_id)
        if trigger is None:
            return
        trigger.last_fired_slot = fired_slot
        if trigger.cron_expr:
            trigger.next_run_at = compute_next_run(trigger.cron_expr, trigger.timezone or "UTC", after=fired_slot)
        trigger.locked_by = None
        trigger.locked_at = None
        await self.mark_attempt(trigger, success=success, task_id=task_id, session_id=session_id, error=error, payload=payload)
        self._sync_config(trigger)
        await self.db.commit()

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
    ) -> tuple[str, Optional[JoySafeterTask], Optional[uuid.UUID], bool, Optional[str]]:
        if not trigger.enabled:
            return "skipped", None, None, False, "trigger disabled"
        if trigger.type != "webhook":
            return "skipped", None, None, False, "trigger is not webhook"
        if not payload_filter_matches(trigger.filter, payload):
            await self.mark_attempt(trigger, success=True, payload=payload)
            return "skipped", None, None, False, "delivery did not match filter"
        agent, environment_ref = await JoySafeterScheduleService(self.db).resolve_runnable_target(
            agent_id=trigger.agent_id,
            project_id=trigger.project_id,
            environment_ref=trigger.environment_ref,
        )
        body_hash = hashlib.sha256(raw_body + auth_fingerprint.encode("utf-8")).hexdigest()
        delivery_key = delivery_id or body_hash
        idempotency_key = f"trigger:webhook:{trigger.id}:{delivery_key}"
        rendered_prompt = render_prompt_template(trigger.prompt_template, payload)
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
                metadata={"trigger_id": str(trigger.id), "trigger_type": "webhook"},
            ),
            enforce_user_quota=True,
        )
        await self.mark_attempt(trigger, success=True, task_id=result.task.id, session_id=result.session.id, payload=payload)
        return ("fired" if result.created else "deduped"), result.task, result.session.id, not result.created, None
