import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.app_errors import RequestValidationAppError

pytestmark = pytest.mark.no_db


def _trigger(**overrides) -> JoySafeterTrigger:
    data = {
        "name": f"trigger-{uuid.uuid4()}",
        "type": "cron",
        "agent_id": uuid.uuid4(),
        "prompt_template": "run",
        "enabled": True,
        "session_mode": "fresh",
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "run_at": None,
        "concurrency_policy": "allow",
        "filter": {},
        "config": {},
        "last_payload": {},
        "project_id": "proj-test",
        "user_id": "owner",
        "org_id": "org-test",
    }
    data.update(overrides)
    return JoySafeterTrigger(**data)


def _assert_invalid(trigger: JoySafeterTrigger, fields: dict, code: str) -> None:
    with pytest.raises(RequestValidationAppError) as exc_info:
        JoySafeterTriggerService(None)._validate_update_candidate(trigger, fields)  # type: ignore[arg-type]
    assert exc_info.value.code == code


def test_update_cannot_leave_cron_without_schedule_source():
    _assert_invalid(
        _trigger(type="cron", cron_expr="0 9 * * *", run_at=None),
        {"cron_expr": None},
        "TRIGGER_CRON_SCHEDULE_REQUIRED",
    )


def test_update_can_switch_cron_to_future_one_off():
    JoySafeterTriggerService(None)._validate_update_candidate(  # type: ignore[arg-type]
        _trigger(type="cron", cron_expr="0 9 * * *", run_at=None),
        {"cron_expr": None, "run_at": datetime.now(timezone.utc) + timedelta(hours=1)},
    )


def test_update_rejects_keyed_session_without_key():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"session_mode": "keyed"},
        "TRIGGER_SESSION_KEY_REQUIRED",
    )


def test_update_rejects_empty_webhook_auth_methods():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"auth_methods": []},
        "TRIGGER_AUTH_METHODS_REQUIRED",
    )
