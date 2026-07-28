from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger, TriggerConcurrencyPolicy
from app.joysafeter_domain.services.joysafeter_trigger_webhook_auth_service import WebhookAuthService
from app.joysafeter_domain.triggers import get_provider
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone

_SUPPORTED_TRIGGER_TYPES = frozenset({"cron", "webhook"})
_SUPPORTED_SESSION_MODES = frozenset({"fresh", "reuse", "pinned", "keyed"})
_SUPPORTED_CONCURRENCY_POLICIES = frozenset(policy.value for policy in TriggerConcurrencyPolicy)


@dataclass(frozen=True)
class TriggerUpdatePlan:
    fields: dict[str, Any]
    next_environment_ref: Optional[str]
    should_resolve_target: bool
    secret_ref_to_verify: Optional[str]
    recompute_next_run: bool
    is_reenable: bool

    def apply_to(self, trigger: JoySafeterTrigger) -> None:
        for key, value in self.fields.items():
            if key in {"auth_methods", "dedupe_header"}:
                config = dict(trigger.config or {})
                config[key] = value
                trigger.config = config
            elif hasattr(trigger, key):
                setattr(trigger, key, value)


class TriggerConfigPolicy:
    @staticmethod
    def build_config(*, type: str, **fields: Any) -> dict[str, Any]:
        return get_provider(type).build_config(**fields)

    @classmethod
    def sync_config(cls, trigger: JoySafeterTrigger) -> None:
        trigger.config = cls.build_config(
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

    @staticmethod
    def webhook_auth_methods(config: Any) -> frozenset[str]:
        return WebhookAuthService.auth_methods(config)

    @classmethod
    def validate_create_fields(
        cls,
        *,
        type: str,
        session_mode: str,
        pinned_session_id: Any,
        session_key: Optional[str],
        cron_expr: Optional[str],
        run_at: Optional[datetime],
        timezone_name: str,
        concurrency_policy: str,
        secret_ref: Optional[str],
        secret_key: Optional[str],
        auth_methods: Optional[list[str]],
    ) -> None:
        cls._validate_trigger_type(type)
        cls._validate_session_fields(
            session_mode=session_mode,
            pinned_session_id=pinned_session_id,
            session_key=session_key,
        )
        cls._validate_concurrency_policy(concurrency_policy)
        cls._validate_schedule_fields(
            trigger_type=type,
            cron_expr=cron_expr,
            run_at=run_at,
            timezone_name=timezone_name,
            cron_expr_was_provided=bool(cron_expr),
            timezone_was_provided=timezone_name not in (None, "UTC"),
            concurrency_policy_was_provided=concurrency_policy != "allow",
            run_at_was_provided=True,
            last_fired_slot=None,
        )
        cls._validate_webhook_fields(
            trigger_type=type,
            secret_ref=secret_ref,
            secret_key=secret_key,
            config={"auth_methods": auth_methods},
        )

    @classmethod
    def validate_update_candidate(cls, trigger: JoySafeterTrigger, fields: dict[str, Any]) -> None:
        cls.plan_update(trigger, fields)

    @classmethod
    def plan_update(cls, trigger: JoySafeterTrigger, fields: dict[str, Any]) -> TriggerUpdatePlan:
        session_mode = fields["session_mode"] if "session_mode" in fields else trigger.session_mode
        pinned_session_id = fields["pinned_session_id"] if "pinned_session_id" in fields else trigger.pinned_session_id
        session_key = fields["session_key"] if "session_key" in fields else trigger.session_key
        cls._validate_session_fields(
            session_mode=session_mode,
            pinned_session_id=pinned_session_id,
            session_key=session_key,
        )
        concurrency_policy = fields["concurrency_policy"] if "concurrency_policy" in fields else trigger.concurrency_policy
        cls._validate_concurrency_policy(concurrency_policy)

        cron_expr = fields["cron_expr"] if "cron_expr" in fields else trigger.cron_expr
        run_at = fields["run_at"] if "run_at" in fields else trigger.run_at
        timezone_name = fields["timezone"] if "timezone" in fields else (trigger.timezone or "UTC")
        cls._validate_schedule_fields(
            trigger_type=trigger.type,
            cron_expr=cron_expr,
            run_at=run_at,
            timezone_name=timezone_name,
            cron_expr_was_provided="cron_expr" in fields,
            timezone_was_provided="timezone" in fields,
            concurrency_policy_was_provided="concurrency_policy" in fields,
            run_at_was_provided="run_at" in fields,
            last_fired_slot=trigger.last_fired_slot,
        )

        if trigger.type == "webhook":
            config = dict(trigger.config or {})
            if "auth_methods" in fields:
                config["auth_methods"] = fields["auth_methods"]
            cls._validate_webhook_fields(
                trigger_type=trigger.type,
                secret_ref=fields["secret_ref"] if "secret_ref" in fields else trigger.secret_ref,
                secret_key=fields["secret_key"] if "secret_key" in fields else trigger.secret_key,
                config=config,
            )
        return TriggerUpdatePlan(
            fields=dict(fields),
            next_environment_ref=fields["environment_ref"] if "environment_ref" in fields else trigger.environment_ref,
            should_resolve_target="environment_ref" in fields or fields.get("enabled") is True,
            secret_ref_to_verify=fields["secret_ref"] if trigger.type == "webhook" and "secret_ref" in fields else None,
            recompute_next_run=trigger.type == "cron" and any(
                key in fields for key in ("cron_expr", "timezone", "run_at", "enabled")
            ),
            is_reenable=fields.get("enabled") is True,
        )

    @staticmethod
    def _validate_trigger_type(trigger_type: str) -> None:
        if trigger_type not in _SUPPORTED_TRIGGER_TYPES:
            raise RequestValidationAppError(
                code="TRIGGER_TYPE_UNSUPPORTED",
                message=f"Unsupported trigger type: {trigger_type}",
                data={"type": trigger_type, "supported": sorted(_SUPPORTED_TRIGGER_TYPES)},
                user_action="fix_input",
            )

    @staticmethod
    def _validate_concurrency_policy(concurrency_policy: str) -> None:
        if concurrency_policy not in _SUPPORTED_CONCURRENCY_POLICIES:
            raise RequestValidationAppError(
                code="TRIGGER_CONCURRENCY_POLICY_INVALID",
                message=f"Invalid concurrency policy: {concurrency_policy}",
                data={"concurrency_policy": concurrency_policy, "supported": sorted(_SUPPORTED_CONCURRENCY_POLICIES)},
                user_action="fix_input",
            )

    @staticmethod
    def _validate_session_fields(
        *,
        session_mode: str,
        pinned_session_id: Any,
        session_key: Optional[str],
    ) -> None:
        if session_mode not in _SUPPORTED_SESSION_MODES:
            raise RequestValidationAppError(
                code="TRIGGER_SESSION_MODE_INVALID",
                message=f"Invalid session mode: {session_mode}",
                data={"session_mode": session_mode, "supported": sorted(_SUPPORTED_SESSION_MODES)},
                user_action="fix_input",
            )
        if session_mode == "pinned" and pinned_session_id is None:
            raise RequestValidationAppError(
                code="TRIGGER_PINNED_SESSION_REQUIRED",
                message="pinned_session_id is required when session_mode is pinned",
                data={"session_mode": session_mode},
                user_action="fix_input",
            )
        if session_mode == "keyed" and not (session_key or "").strip():
            raise RequestValidationAppError(
                code="TRIGGER_SESSION_KEY_REQUIRED",
                message="session_key is required when session_mode is keyed",
                data={"session_mode": session_mode},
                user_action="fix_input",
            )

    @staticmethod
    def _validate_schedule_fields(
        *,
        trigger_type: str,
        cron_expr: Optional[str],
        run_at: Optional[datetime],
        timezone_name: Optional[str],
        cron_expr_was_provided: bool,
        timezone_was_provided: bool,
        concurrency_policy_was_provided: bool,
        run_at_was_provided: bool,
        last_fired_slot: Optional[datetime],
    ) -> None:
        if trigger_type == "cron":
            has_cron = bool(cron_expr)
            has_run_at = run_at is not None
            if has_cron == has_run_at:
                raise RequestValidationAppError(
                    code="TRIGGER_CRON_SCHEDULE_REQUIRED",
                    message="cron trigger requires exactly one of cron_expr or run_at",
                    data={"cron_expr": cron_expr, "run_at": run_at.isoformat() if run_at else None},
                    user_action="fix_input",
                )
            if not validate_timezone(timezone_name or "UTC"):
                raise RequestValidationAppError(
                    code="TRIGGER_INVALID_TIMEZONE",
                    message=f"Invalid timezone: {timezone_name}",
                    data={"timezone": timezone_name},
                    user_action="fix_input",
                )
            if cron_expr and not validate_cron(cron_expr):
                raise RequestValidationAppError(
                    code="TRIGGER_INVALID_CRON_EXPR",
                    message=f"Invalid cron expression: {cron_expr}",
                    data={"cron_expr": cron_expr},
                    user_action="fix_input",
                )
            if run_at is not None and (run_at_was_provided or last_fired_slot is None):
                candidate_run_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
                if candidate_run_at <= datetime.now(timezone.utc):
                    raise RequestValidationAppError(
                        code="TRIGGER_RUN_AT_IN_PAST",
                        message="run_at must be in the future",
                        data={"run_at": run_at.isoformat()},
                        user_action="fix_input",
                    )
        else:
            if run_at_was_provided and run_at is not None:
                raise RequestValidationAppError(
                    code="TRIGGER_RUN_AT_NOT_ALLOWED",
                    message="run_at is only valid for cron triggers",
                    data={"type": trigger_type},
                    user_action="fix_input",
                )
            for field_name, is_present in (
                ("cron_expr", cron_expr_was_provided and bool(cron_expr)),
                ("timezone", timezone_was_provided),
                ("concurrency_policy", concurrency_policy_was_provided),
            ):
                if is_present:
                    raise RequestValidationAppError(
                        code="TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
                        message=f"{field_name} is only valid for cron triggers",
                        data={"type": trigger_type, "field": field_name},
                        user_action="fix_input",
                    )

    @classmethod
    def _validate_webhook_fields(
        cls,
        *,
        trigger_type: str,
        secret_ref: Optional[str],
        secret_key: Optional[str],
        config: dict[str, Any],
    ) -> None:
        if trigger_type != "webhook":
            return
        auth_methods = cls.webhook_auth_methods(config)
        if not secret_ref:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_REQUIRED",
                message="secret_ref is required when type is webhook",
                data={"type": trigger_type},
                user_action="fix_input",
            )
        if not secret_key:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_KEY_REQUIRED",
                message="secret_key is required when type is webhook",
                data={"type": trigger_type},
                user_action="fix_input",
            )
        if not auth_methods:
            raw_auth_methods = config.get("auth_methods")
            code = "TRIGGER_AUTH_METHODS_REQUIRED" if raw_auth_methods == [] else "TRIGGER_AUTH_METHODS_INVALID"
            message = "auth_methods must not be empty" if raw_auth_methods == [] else "auth_methods contains unsupported values"
            raise RequestValidationAppError(
                code=code,
                message=message,
                data={"type": trigger_type},
                user_action="fix_input",
            )
