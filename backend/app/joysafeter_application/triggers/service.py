from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.webhook_auth_service import WebhookAuthService
from app.joysafeter_application.triggers.fire_service import FireResult, TriggerFireService
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialId,
    EnvironmentId,
    OrganizationId,
    ProjectId,
    SessionId,
    TriggerId,
    UserId,
)


class TriggerApplicationService(JoySafeterTriggerService):
    """Application command surface for Trigger management, authentication, and firing."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        credential_audit_actor: CredentialAuditActor,
    ) -> None:
        super().__init__(db)
        self._credential_audit_actor = credential_audit_actor

    def _fire_service(self) -> TriggerFireService:
        return TriggerFireService(
            self.db,
            project_trigger_block_reason=self.project_trigger_block_reason,
            resolve_runnable_target=self.resolve_runnable_target,
            mark_attempt=self.mark_attempt,
            audit_actor=self._credential_audit_actor,
        )

    async def _notify_scheduler(self, trigger: JoySafeterTrigger) -> None:
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
        return await WebhookAuthService(
            self.db,
            audit_actor=self._credential_audit_actor,
        ).resolve_webhook_secret(trigger)

    @staticmethod
    def _is_trigger_name_integrity_error(exc: IntegrityError) -> bool:
        message = str(exc.orig or exc).lower()
        return (
            "uq_joysafeter_triggers_project_name" in message
            or "uq_joysafeter_triggers_global_name" in message
            or (
                "joysafeter_triggers" in message
                and "project_id" in message
                and "name" in message
                and "unique" in message
            )
        )

    @staticmethod
    def _trigger_name_conflict(name: str) -> ResourceConflictError:
        return ResourceConflictError(
            code="TRIGGER_NAME_EXISTS",
            message=f"A trigger named '{name}' already exists in this project",
            data={"name": name},
            user_action="fix_input",
        )

    async def _commit_or_raise_name_conflict(self, name: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if self._is_trigger_name_integrity_error(exc):
                raise self._trigger_name_conflict(name) from exc
            raise

    async def create(
        self,
        *,
        name: str,
        agent_id: AgentId,
        prompt_template: str,
        type: str = "webhook",
        environment_id: Optional[EnvironmentId] = None,
        description: Optional[str] = None,
        enabled: bool = True,
        session_mode: str = "fresh",
        pinned_session_id: Optional[SessionId] = None,
        session_key: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
        cron_expr: Optional[str] = None,
        timezone: str = "UTC",
        run_at: Optional[datetime] = None,
        concurrency_policy: str = "allow",
        webhook_auth_credential_id: Optional[CredentialId] = None,
        webhook_auth_field: Optional[str] = "WEBHOOK_SECRET",
        auth_methods: Optional[list[str]] = None,
        dedupe_header: Optional[str] = "x-joysafeter-delivery",
        project_id: ProjectId | None = None,
        user_id: UserId | None = None,
        org_id: OrganizationId | None = None,
    ) -> JoySafeterTrigger:
        TriggerConfigPolicy.validate_create_fields(
            type=type,
            session_mode=session_mode,
            pinned_session_id=pinned_session_id,
            session_key=session_key,
            cron_expr=cron_expr,
            run_at=run_at,
            timezone_name=timezone,
            concurrency_policy=concurrency_policy,
            webhook_auth_credential_id=webhook_auth_credential_id,
            webhook_auth_field=webhook_auth_field,
            auth_methods=auth_methods,
        )
        if type != "webhook":
            webhook_auth_credential_id = None
            webhook_auth_field = None
            auth_methods = None
            dedupe_header = None
        if await self.get_by_name(name, project_id) is not None:
            raise self._trigger_name_conflict(name)
        await self.resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_id=environment_id,
        )
        if type == "webhook" and webhook_auth_credential_id and webhook_auth_field:
            application = compose_credential_application(
                self.db,
                auto_commit=False,
                audit_actor=self._credential_audit_actor,
            )
            await application.uow.credentials.lock_credential(
                webhook_auth_credential_id,
                project_id=project_id,
            )
            await WebhookAuthService(
                self.db,
                audit_actor=self._credential_audit_actor,
            ).resolve_secret_value(
                webhook_auth_credential_id=webhook_auth_credential_id,
                webhook_auth_field=webhook_auth_field,
                project_id=project_id,
                auth_methods=auth_methods,
            )
        next_run_at = None
        trigger = JoySafeterTrigger(
            id=TriggerId.new(),
            name=name,
            type=type,
            agent_id=agent_id,
            prompt_template=prompt_template,
            environment_id=environment_id,
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
            webhook_auth_credential_id=webhook_auth_credential_id,
            webhook_auth_field=webhook_auth_field,
            config=self._config_for(
                type=type,
                cron_expr=cron_expr,
                timezone=timezone,
                concurrency_policy=concurrency_policy,
                next_run_at=next_run_at.isoformat() if next_run_at else None,
                webhook_auth_credential_id=webhook_auth_credential_id,
                webhook_auth_field=webhook_auth_field,
                auth_methods=auth_methods,
                dedupe_header=dedupe_header,
            ),
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
        )
        if type == "cron":
            trigger.next_run_at = await self._next_run_or_pause(trigger)
            self._sync_config(trigger)
        self.db.add(trigger)
        await self._commit_or_raise_name_conflict(name)
        await self.db.refresh(trigger)
        await self._notify_scheduler(trigger)
        return trigger

    async def update(
        self,
        trigger_id: TriggerId,
        project_id: ProjectId | None,
        **fields: Any,
    ) -> Optional[JoySafeterTrigger]:
        TriggerConfigPolicy.validate_update_fields_before_lookup(fields)
        trigger = await self._get_for_update(trigger_id, project_id=project_id)
        if trigger is None:
            return None
        plan = TriggerConfigPolicy.plan_update(trigger, fields)
        if "name" in fields and fields["name"] != trigger.name:
            existing = await self.get_by_name(fields["name"], project_id)
            if existing is not None and existing.id != trigger_id:
                raise self._trigger_name_conflict(fields["name"])
        if plan.should_resolve_target:
            await self.resolve_runnable_target(
                agent_id=trigger.agent_id,
                project_id=trigger.project_id,
                environment_id=plan.next_environment_id,
            )
        if plan.webhook_auth_credential_id_to_verify is not None and plan.webhook_auth_field_to_verify is not None:
            application = compose_credential_application(
                self.db,
                auto_commit=False,
                audit_actor=self._credential_audit_actor,
            )
            await application.uow.credentials.lock_credential(
                plan.webhook_auth_credential_id_to_verify,
                project_id=trigger.project_id,
            )
            await WebhookAuthService(
                self.db,
                audit_actor=self._credential_audit_actor,
            ).resolve_secret_value(
                webhook_auth_credential_id=plan.webhook_auth_credential_id_to_verify,
                webhook_auth_field=plan.webhook_auth_field_to_verify,
                project_id=trigger.project_id,
                trigger_id=trigger.id,
                auth_methods=(
                    plan.fields.get("auth_methods")
                    if "auth_methods" in plan.fields
                    else (trigger.config or {}).get("auth_methods")
                ),
            )
        plan.apply_to(trigger)
        if plan.recompute_next_run:
            trigger.next_run_at = await self._next_run_or_pause(trigger)
        if plan.is_reenable:
            trigger.consecutive_failures = 0
            trigger.auto_disabled_at = None
            trigger.disabled_reason = None
            trigger.slot_attempts = 0
            trigger.pending_slot_at = None
            if trigger.type == "cron" and trigger.next_run_at is None:
                trigger.next_run_at = await self._next_run_or_pause(trigger)
        self._sync_config(trigger)
        await self._commit_or_raise_name_conflict(trigger.name)
        await self.db.refresh(trigger)
        await self._notify_scheduler(trigger)
        return trigger

    @staticmethod
    def _sign(secret: str, body: bytes) -> str:
        return WebhookAuthService.sign(secret, body)

    @staticmethod
    def verify_signature(raw_body: bytes, secret: str, signature_header: Optional[str]) -> bool:
        return WebhookAuthService.verify_signature(raw_body, secret, signature_header)

    @staticmethod
    def verify_token(secret: str, token: Optional[str]) -> bool:
        return WebhookAuthService.verify_token(secret, token)

    @staticmethod
    def _webhook_auth_methods(config: Any) -> frozenset[str]:
        return TriggerConfigPolicy.webhook_auth_methods(config)

    async def verify_webhook_auth(
        self,
        trigger: JoySafeterTrigger,
        raw_body: bytes,
        signature: Optional[str],
        token: Optional[str],
    ) -> bool:
        secret = await self._resolve_webhook_secret(trigger)
        return WebhookAuthService.verify_with_secret(
            config=trigger.config,
            raw_body=raw_body,
            secret=secret,
            signature=signature,
            token=token,
        )

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
        return await self._fire_service().fire_webhook(
            trigger,
            raw_body=raw_body,
            payload=payload,
            delivery_id=delivery_id,
            auth_fingerprint=auth_fingerprint,
            ignore_enabled=ignore_enabled,
        )

    async def fire_manual(
        self,
        trigger: JoySafeterTrigger,
        *,
        idempotency_header: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> FireResult:
        return await self._fire_service().fire_manual(
            trigger,
            idempotency_header=idempotency_header,
            now=now,
        )

    async def build_webhook_curl(
        self,
        trigger: JoySafeterTrigger,
        *,
        url: str,
        sample_body: Optional[dict[str, Any]] = None,
    ) -> str:
        secret = await self._resolve_webhook_secret(trigger)
        return WebhookAuthService.build_signed_curl(secret=secret, url=url, sample_body=sample_body)
