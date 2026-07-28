"""Trigger-type provider registry: dispatch seam for cron/webhook/manual.

Pure unit tests (no DB): registration, config snapshots equal to the legacy
hardcoded dicts, exactly-once key derivation (including the attempt suffix used
by slot retries), and rejection of unknown types.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.triggers import get_provider, supported_kinds
from app.joysafeter_shared.common.app_errors import RequestValidationAppError

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


def test_cron_build_config_matches_legacy_shape():
    cfg = get_provider("cron").build_config(cron_expr="*/5 * * * *")
    assert cfg == {
        "cron_expr": "*/5 * * * *",
        "timezone": "UTC",
        "concurrency_policy": "allow",
        "next_run_at": None,
        "last_fired_slot": None,
    }


def test_webhook_build_config_defaults():
    cfg = get_provider("webhook").build_config(secret_ref="hook")
    assert cfg == {
        "secret_ref": "hook",
        "secret_key": "WEBHOOK_SECRET",
        "auth_methods": ["hmac", "bearer", "token"],
        "dedupe_header": "x-joysafeter-delivery",
    }


def test_manual_build_config_empty():
    assert get_provider("manual").build_config() == {}


def test_cron_idempotency_key_attempt_suffix():
    provider = get_provider("cron")
    trigger = _trigger()
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    epoch = int(slot.timestamp())
    # Attempt 0 keeps the legacy key (backward compatible with existing rows).
    assert provider.idempotency_key(trigger, fired_slot=slot, attempt=0) == f"trigger:cron:TID:{epoch}"
    # Retries get a distinct key so they re-fire instead of deduping against the
    # FAILED task that holds the attempt-0 key.
    assert provider.idempotency_key(trigger, fired_slot=slot, attempt=2) == f"trigger:cron:TID:{epoch}:r2"


def test_webhook_idempotency_key():
    key = get_provider("webhook").idempotency_key(_trigger(), delivery_key="D1")
    assert key == "trigger:webhook:TID:D1"


def test_cron_build_payload_shape():
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    payload = get_provider("cron").build_payload(_trigger(), fired_slot=slot)
    assert payload["trigger"] == {"type": "cron", "source": "cron"}
    assert payload["schedule"]["cron_expr"] == "0 0 * * *"
    assert payload["schedule"]["fired_at"] == slot.isoformat()
