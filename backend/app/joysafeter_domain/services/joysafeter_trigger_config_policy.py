from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger, TriggerConcurrencyPolicy
from app.joysafeter_domain.triggers import get_provider, supported_kinds
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.ids import CredentialId, EnvironmentId, SessionId
from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone

_SUPPORTED_TRIGGER_TYPES = frozenset(supported_kinds())
_SUPPORTED_SESSION_MODES = frozenset({"fresh", "reuse", "pinned", "keyed"})
_SUPPORTED_CONCURRENCY_POLICIES = frozenset(policy.value for policy in TriggerConcurrencyPolicy)
_SUPPORTED_WEBHOOK_AUTH_METHODS = frozenset({"hmac", "bearer", "token"})


@dataclass(frozen=True)
class TriggerUpdatePlan:
    fields: dict[str, Any]
    next_environment_id: Optional[EnvironmentId]
    should_resolve_target: bool
    webhook_auth_credential_id_to_verify: Optional[CredentialId]
    webhook_auth_field_to_verify: Optional[str]
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
            webhook_auth_credential_id=trigger.webhook_auth_credential_id,
            webhook_auth_field=trigger.webhook_auth_field or "WEBHOOK_SECRET",
            auth_methods=(trigger.config or {}).get("auth_methods"),
            dedupe_header=(trigger.config or {}).get("dedupe_header"),
        )

    @staticmethod
    def webhook_auth_methods(config: Any) -> frozenset[str]:
        if not isinstance(config, dict):
            return frozenset()
        configured = config.get("auth_methods")
        if not isinstance(configured, list) or not configured:
            return frozenset()
        normalized: set[str] = set()
        for method in configured:
            if not isinstance(method, str):
                return frozenset()
            normalized_method = method.strip().lower()
            if normalized_method not in _SUPPORTED_WEBHOOK_AUTH_METHODS:
                return frozenset()
            normalized.add(normalized_method)
        return frozenset(normalized)

    @classmethod
    def validate_create_fields(
        cls,
        *,
        type: str,
        session_mode: str,
        pinned_session_id: SessionId | None,
        session_key: Optional[str],
        cron_expr: Optional[str],
        run_at: Optional[datetime],
        timezone_name: str,
        concurrency_policy: str,
        webhook_auth_credential_id: Optional[CredentialId],
        webhook_auth_field: Optional[str],
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
            webhook_auth_credential_id=webhook_auth_credential_id,
            webhook_auth_field=webhook_auth_field,
            config={"auth_methods": auth_methods},
        )

    @classmethod
    def validate_update_candidate(cls, trigger: JoySafeterTrigger, fields: dict[str, Any]) -> None:
        cls.plan_update(trigger, fields)

    @classmethod
    def validate_update_fields_before_lookup(cls, fields: dict[str, Any]) -> None:
        if "auth_methods" in fields:
            cls._validate_auth_methods(fields["auth_methods"], trigger_type="webhook")

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
        concurrency_policy = (
            fields["concurrency_policy"] if "concurrency_policy" in fields else trigger.concurrency_policy
        )
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
                webhook_auth_credential_id=(
                    fields["webhook_auth_credential_id"]
                    if "webhook_auth_credential_id" in fields
                    else trigger.webhook_auth_credential_id
                ),
                webhook_auth_field=(
                    fields["webhook_auth_field"] if "webhook_auth_field" in fields else trigger.webhook_auth_field
                ),
                config=config,
            )
        verify_secret = trigger.type == "webhook" and bool(
            {"webhook_auth_credential_id", "webhook_auth_field", "auth_methods"} & fields.keys()
        )
        effective_credential_id = fields.get("webhook_auth_credential_id", trigger.webhook_auth_credential_id)
        effective_field = fields.get("webhook_auth_field", trigger.webhook_auth_field)
        return TriggerUpdatePlan(
            fields=dict(fields),
            next_environment_id=fields["environment_id"] if "environment_id" in fields else trigger.environment_id,
            should_resolve_target="environment_id" in fields or fields.get("enabled") is True,
            webhook_auth_credential_id_to_verify=effective_credential_id if verify_secret else None,
            webhook_auth_field_to_verify=effective_field if verify_secret else None,
            recompute_next_run=trigger.type == "cron"
            and any(key in fields for key in ("cron_expr", "timezone", "run_at", "enabled")),
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
        pinned_session_id: SessionId | None,
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
        webhook_auth_credential_id: Optional[CredentialId],
        webhook_auth_field: Optional[str],
        config: dict[str, Any],
    ) -> None:
        if trigger_type != "webhook":
            return
        if not webhook_auth_credential_id:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_REQUIRED",
                message="webhook_auth_credential_id is required when type is webhook",
                data={"type": trigger_type},
                user_action="fix_input",
            )
        if not webhook_auth_field:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_KEY_REQUIRED",
                message="webhook_auth_field is required when type is webhook",
                data={"type": trigger_type},
                user_action="fix_input",
            )
        raw_auth_methods = config.get("auth_methods") if isinstance(config, dict) else None
        cls._validate_auth_methods(raw_auth_methods, trigger_type=trigger_type)

    @staticmethod
    def _validate_auth_methods(raw_auth_methods: object, *, trigger_type: str) -> None:
        is_empty = raw_auth_methods is None
        if not is_empty:
            try:
                is_empty = len(raw_auth_methods) == 0  # type: ignore[arg-type]
            except TypeError:
                is_empty = False
        if is_empty:
            raise RequestValidationAppError(
                code="TRIGGER_AUTH_METHODS_REQUIRED",
                message="auth_methods is required and must not be empty",
                data={"type": trigger_type},
                user_action="fix_input",
            )
        if not isinstance(raw_auth_methods, list) or any(
            not isinstance(method, str) or method not in _SUPPORTED_WEBHOOK_AUTH_METHODS for method in raw_auth_methods
        ):
            raise RequestValidationAppError(
                code="TRIGGER_AUTH_METHODS_INVALID",
                message="auth_methods contains an unsupported method",
                data={"type": trigger_type},
                user_action="fix_input",
            )
