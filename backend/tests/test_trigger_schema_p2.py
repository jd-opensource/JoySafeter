"""P2 trigger config policy: keyed session_key, cron XOR run_at, run_at rules."""

from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.ids import CredentialId

pytestmark = pytest.mark.no_db

_FUTURE = datetime.now(timezone.utc) + timedelta(hours=1)
_PAST = datetime.now(timezone.utc) - timedelta(hours=1)
_CRED_ID = CredentialId.new()


def _validate(**overrides):
    fields = {
        "type": "cron",
        "session_mode": "fresh",
        "pinned_session_id": None,
        "session_key": None,
        "cron_expr": None,
        "run_at": None,
        "timezone_name": "UTC",
        "concurrency_policy": "allow",
        "webhook_auth_credential_id": None,
        "webhook_auth_field": "WEBHOOK_SECRET",
        "auth_methods": ["hmac", "bearer", "token"],
    }
    fields.update(overrides)
    TriggerConfigPolicy.validate_create_fields(**fields)


def _assert_invalid(code: str, **overrides):
    with pytest.raises(RequestValidationAppError) as exc_info:
        _validate(**overrides)
    assert exc_info.value.code == code


def test_cron_requires_cron_expr_or_run_at():
    _assert_invalid("TRIGGER_CRON_SCHEDULE_REQUIRED")


def test_unsupported_trigger_type_gets_semantic_error():
    _assert_invalid("TRIGGER_TYPE_UNSUPPORTED", type="event")


def test_invalid_session_mode_gets_semantic_error():
    _assert_invalid("TRIGGER_SESSION_MODE_INVALID", type="webhook", webhook_auth_credential_id=_CRED_ID, session_mode="loop")


def test_invalid_concurrency_policy_gets_semantic_error():
    _assert_invalid("TRIGGER_CONCURRENCY_POLICY_INVALID", cron_expr="*/5 * * * *", concurrency_policy="queue")


def test_invalid_auth_method_gets_semantic_error():
    _assert_invalid("TRIGGER_AUTH_METHODS_INVALID", type="webhook", webhook_auth_credential_id=_CRED_ID, auth_methods=["magic-link"])


def test_legacy_token_auth_method_remains_valid():
    _validate(type="webhook", webhook_auth_credential_id=_CRED_ID, auth_methods=["token"])


def test_cron_rejects_both_cron_expr_and_run_at():
    _assert_invalid("TRIGGER_CRON_SCHEDULE_REQUIRED", cron_expr="* * * * *", run_at=_FUTURE)


def test_cron_accepts_cron_expr_only():
    _validate(cron_expr="*/5 * * * *")


def test_cron_accepts_run_at_only():
    _validate(run_at=_FUTURE)


def test_manual_accepts_no_schedule_or_webhook_secret():
    _validate(type="manual")


def test_run_at_must_be_future():
    _assert_invalid("TRIGGER_RUN_AT_IN_PAST", run_at=_PAST)


def test_run_at_only_valid_for_cron():
    _assert_invalid(
        "TRIGGER_RUN_AT_NOT_ALLOWED",
        type="webhook",
        webhook_auth_credential_id=_CRED_ID,
        run_at=_FUTURE,
    )


def test_cron_expr_only_valid_for_cron():
    _assert_invalid(
        "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
        type="webhook",
        webhook_auth_credential_id=_CRED_ID,
        cron_expr="*/5 * * * *",
    )


def test_non_default_concurrency_policy_only_valid_for_cron():
    _assert_invalid(
        "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
        type="webhook",
        webhook_auth_credential_id=_CRED_ID,
        concurrency_policy="forbid",
    )


def test_keyed_requires_session_key():
    _assert_invalid(
        "TRIGGER_SESSION_KEY_REQUIRED",
        type="webhook",
        webhook_auth_credential_id=_CRED_ID,
        session_mode="keyed",
    )


def test_keyed_accepts_session_key():
    _validate(
        type="webhook",
        webhook_auth_credential_id=_CRED_ID,
        session_mode="keyed",
        session_key="{{ body.chat_id }}",
    )
