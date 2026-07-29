import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
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


def test_update_rejects_invalid_session_mode():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"session_mode": "loop"},
        "TRIGGER_SESSION_MODE_INVALID",
    )


def test_update_rejects_invalid_concurrency_policy():
    _assert_invalid(
        _trigger(type="cron", cron_expr="0 9 * * *", run_at=None),
        {"concurrency_policy": "queue"},
        "TRIGGER_CONCURRENCY_POLICY_INVALID",
    )


def test_update_rejects_empty_webhook_auth_methods():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"auth_methods": []},
        "TRIGGER_AUTH_METHODS_REQUIRED",
    )


def test_update_allows_legacy_webhook_config_missing_auth_methods():
    JoySafeterTriggerService(None)._validate_update_candidate(  # type: ignore[arg-type]
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={}),
        {"description": "updated"},
    )


def test_update_rejects_unknown_webhook_auth_methods():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"auth_methods": ["hmac", "magic-link"]},
        "TRIGGER_AUTH_METHODS_INVALID",
    )


def test_update_rejects_cron_expr_on_webhook_trigger():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"cron_expr": "*/5 * * * *"},
        "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
    )


def test_update_rejects_concurrency_policy_on_webhook_trigger():
    _assert_invalid(
        _trigger(type="webhook", secret_ref="hook-secret", secret_key="WEBHOOK_SECRET", config={"auth_methods": ["hmac"]}),
        {"concurrency_policy": "forbid"},
        "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
    )


def test_sync_config_preserves_explicit_empty_webhook_auth_methods():
    trigger = _trigger(
        type="webhook",
        secret_ref="hook-secret",
        secret_key="WEBHOOK_SECRET",
        config={"auth_methods": []},
    )

    JoySafeterTriggerService(None)._sync_config(trigger)  # type: ignore[arg-type]

    assert trigger.config["auth_methods"] == []


def test_update_plan_captures_runtime_and_secret_dependency_checks():
    trigger = _trigger(
        type="webhook",
        secret_ref="old-secret",
        secret_key="WEBHOOK_SECRET",
        environment_ref="old-env",
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
    )

    plan = TriggerConfigPolicy.plan_update(
        trigger,
        {"environment_ref": "new-env", "secret_ref": "new-secret", "auth_methods": ["bearer"]},
    )

    assert plan.should_resolve_target is True
    assert plan.next_environment_ref == "new-env"
    assert plan.secret_ref_to_verify == "new-secret"
    assert plan.recompute_next_run is False
    plan.apply_to(trigger)
    assert trigger.environment_ref == "new-env"
    assert trigger.secret_ref == "new-secret"
    assert trigger.config["auth_methods"] == ["bearer"]


def test_update_plan_marks_cron_rearm_and_reenable_intent():
    trigger = _trigger(type="cron", cron_expr="0 9 * * *", run_at=None, next_run_at=None, enabled=False)

    plan = TriggerConfigPolicy.plan_update(trigger, {"enabled": True, "cron_expr": "*/5 * * * *"})

    assert plan.should_resolve_target is True
    assert plan.recompute_next_run is True
    assert plan.is_reenable is True


@pytest.mark.asyncio
async def test_create_rejects_webhook_without_secret_ref_at_domain_boundary():
    with pytest.raises(RequestValidationAppError) as exc_info:
        await _NoDbCreateService(_NoDb()).create(  # type: ignore[arg-type]
            name="unsafe-webhook",
            type="webhook",
            agent_id=uuid.uuid4(),
            prompt_template="run",
            secret_ref=None,
        )

    assert exc_info.value.code == "TRIGGER_SECRET_REQUIRED"


@pytest.mark.asyncio
async def test_create_rejects_cron_without_schedule_at_domain_boundary():
    with pytest.raises(RequestValidationAppError) as exc_info:
        await _NoDbCreateService(_NoDb()).create(  # type: ignore[arg-type]
            name="broken-cron",
            type="cron",
            agent_id=uuid.uuid4(),
            prompt_template="run",
        )

    assert exc_info.value.code == "TRIGGER_CRON_SCHEDULE_REQUIRED"


@pytest.mark.asyncio
async def test_create_rejects_empty_webhook_auth_methods_at_domain_boundary():
    with pytest.raises(RequestValidationAppError) as exc_info:
        await _NoDbCreateService(_NoDb()).create(  # type: ignore[arg-type]
            name="unsafe-webhook",
            type="webhook",
            agent_id=uuid.uuid4(),
            prompt_template="run",
            secret_ref="hook-secret",
            auth_methods=[],
        )

    assert exc_info.value.code == "TRIGGER_AUTH_METHODS_REQUIRED"


@pytest.mark.asyncio
async def test_create_rejects_cron_expr_on_webhook_at_domain_boundary():
    with pytest.raises(RequestValidationAppError) as exc_info:
        await _NoDbCreateService(_NoDb()).create(  # type: ignore[arg-type]
            name="dirty-webhook",
            type="webhook",
            agent_id=uuid.uuid4(),
            prompt_template="run",
            secret_ref="hook-secret",
            cron_expr="*/5 * * * *",
        )

    assert exc_info.value.code == "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_create_manual_trigger_has_no_schedule_or_webhook_config_pollution():
    db = _NoDb()
    trigger = await _NoDbCreateService(db).create(  # type: ignore[arg-type]
        name="manual-only",
        type="manual",
        agent_id=uuid.uuid4(),
        prompt_template="run on demand",
        secret_ref="ignored-webhook-secret",
        secret_key="IGNORED_SECRET_KEY",
        auth_methods=["hmac"],
        dedupe_header="x-ignored-delivery",
    )

    assert db.added is trigger
    assert trigger.type == "manual"
    assert trigger.config == {}
    assert trigger.cron_expr is None
    assert trigger.timezone is None
    assert trigger.run_at is None
    assert trigger.next_run_at is None
    assert trigger.secret_ref is None
    assert trigger.secret_key is None


class _NoDb:
    def __init__(self):
        self.added = None

    def add(self, _value):
        self.added = _value

    async def commit(self):
        pass

    async def refresh(self, _value):
        pass


class _NoDbCreateService(JoySafeterTriggerService):
    async def get_by_name(self, *_args, **_kwargs):
        return None

    async def resolve_runnable_target(self, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4()), None
