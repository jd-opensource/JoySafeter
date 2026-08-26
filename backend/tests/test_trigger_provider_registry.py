"""Trigger-type provider registry contracts for cron, webhook, and manual."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.triggers import get_provider, supported_kinds
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.ids import CredentialId, UserId

pytestmark = pytest.mark.no_db


def _trigger():
    return SimpleNamespace(
        id="TID",
        name="nightly",
        type="cron",
        cron_expr="0 0 * * *",
        timezone="UTC",
        last_fired_slot=None,
    )


def test_all_builtin_kinds_registered():
    assert set(supported_kinds()) == {"cron", "webhook", "manual"}


def test_unknown_kind_raises():
    with pytest.raises(RequestValidationAppError):
        get_provider("event")


def test_cron_build_config_shape():
    cfg = get_provider("cron").build_config(cron_expr="*/5 * * * *")
    assert cfg == {
        "cron_expr": "*/5 * * * *",
        "timezone": "UTC",
        "concurrency_policy": "allow",
        "next_run_at": None,
        "last_fired_slot": None,
    }


def test_webhook_build_config_requires_explicit_auth_methods():
    cred_id = CredentialId.new()
    cfg = get_provider("webhook").build_config(webhook_auth_credential_id=cred_id)
    assert cfg == {
        "webhook_auth_credential_id": str(cred_id),
        "webhook_auth_field": "WEBHOOK_SECRET",
        "auth_methods": None,
        "dedupe_header": "x-joysafeter-delivery",
    }


def test_webhook_build_config_preserves_explicit_empty_auth_methods():
    cfg = get_provider("webhook").build_config(webhook_auth_credential_id=CredentialId.new(), auth_methods=[])
    assert cfg["auth_methods"] == []


def test_webhook_build_config_rejects_non_typed_credential_id():
    with pytest.raises(TypeError, match="webhook auth credential ID must be CredentialId"):
        get_provider("webhook").build_config(webhook_auth_credential_id="credential-not-typed")


def test_manual_build_config_empty():
    assert get_provider("manual").build_config() == {}


def test_cron_idempotency_key_attempt_suffix():
    provider = get_provider("cron")
    trigger = _trigger()
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    epoch = int(slot.timestamp())
    # Attempt 0 is the base logical-slot key.
    assert provider.idempotency_key(trigger, fired_slot=slot, attempt=0) == f"trigger:cron:TID:{epoch}"
    # Retries get a distinct key so they re-fire instead of deduping against the
    # FAILED task that holds the attempt-0 key.
    assert provider.idempotency_key(trigger, fired_slot=slot, attempt=2) == f"trigger:cron:TID:{epoch}:r2"


def test_webhook_idempotency_key():
    key = get_provider("webhook").idempotency_key(_trigger(), delivery_key="D1")
    assert key == "trigger:webhook:TID:D1"


def test_webhook_idempotency_key_hashes_oversized_delivery_key():
    key = get_provider("webhook").idempotency_key(_trigger(), delivery_key="x" * 10_000)
    assert key.startswith("trigger:webhook:TID:sha256:")
    assert len(key) < 160


def test_manual_idempotency_key_hashes_oversized_external_header():
    key = get_provider("manual").idempotency_key(
        _trigger(),
        idempotency_header="x" * 10_000,
        user_id=UserId.new(),
        now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    )
    assert key.startswith("trigger:TID:manual:sha256:")
    assert len(key) < 160


def test_cron_build_payload_shape():
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    payload = get_provider("cron").build_payload(_trigger(), fired_slot=slot)
    assert payload["trigger"] == {"type": "cron", "source": "cron"}
    assert payload["cron"]["cron_expr"] == "0 0 * * *"
    assert payload["cron"]["fired_at"] == slot.isoformat()
