import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_trigger import (
    TriggerCreateRequest,
    TriggerResponse,
    TriggerRunResponse,
    TriggerUpdateRequest,
)

pytestmark = pytest.mark.no_db


def test_cron_trigger_create_trims_strings_before_validation() -> None:
    req = TriggerCreateRequest(
        name="  Daily report  ",
        type="  cron  ",
        agent_id=uuid.uuid4(),
        prompt_template="  summarize yesterday  ",
        cron_expr="  */5 * * * *  ",
        timezone="  UTC  ",
        concurrency_policy="  forbid  ",
        environment_ref="   ",
        description="  ",
    )

    assert req.name == "Daily report"
    assert req.type == "cron"
    assert req.prompt_template == "summarize yesterday"
    assert req.cron_expr == "*/5 * * * *"
    assert req.timezone == "UTC"
    assert req.concurrency_policy == "forbid"
    assert req.environment_ref is None
    assert req.description is None


def test_trigger_create_schema_leaves_business_invariants_to_domain_policy() -> None:
    req = TriggerCreateRequest(
        name="Daily report",
        type="cron",
        agent_id=uuid.uuid4(),
        prompt_template="do work",
    )

    assert req.type == "cron"
    assert req.cron_expr is None
    assert req.run_at is None


def test_trigger_create_schema_accepts_business_enum_wire_values_for_domain_policy() -> None:
    req = TriggerCreateRequest(
        name="Daily report",
        type="event",
        agent_id=uuid.uuid4(),
        prompt_template="do work",
        session_mode="loop",
        concurrency_policy="queue",
        auth_methods=["magic-link"],
    )

    assert req.type == "event"
    assert req.session_mode == "loop"
    assert req.concurrency_policy == "queue"
    assert req.auth_methods == ["magic-link"]


def test_trigger_update_schema_accepts_business_enum_wire_values_for_domain_policy() -> None:
    req = TriggerUpdateRequest(
        session_mode="loop",
        concurrency_policy="queue",
        auth_methods=["magic-link"],
    )

    assert req.session_mode == "loop"
    assert req.concurrency_policy == "queue"
    assert req.auth_methods == ["magic-link"]


def test_trigger_create_rejects_whitespace_only_required_strings() -> None:
    with pytest.raises(ValidationError):
        TriggerCreateRequest(
            name="   ",
            type="cron",
            agent_id=uuid.uuid4(),
            prompt_template="do work",
            cron_expr="*/5 * * * *",
        )

    with pytest.raises(ValidationError):
        TriggerCreateRequest(
            name="Daily report",
            type="cron",
            agent_id=uuid.uuid4(),
            prompt_template="   ",
            cron_expr="*/5 * * * *",
        )


def test_trigger_update_rejects_explicit_null_for_non_nullable_fields() -> None:
    for field in (
        "name",
        "prompt_template",
        "timezone",
        "timeout_sec",
        "max_retries",
        "concurrency_policy",
        "enabled",
    ):
        with pytest.raises(ValidationError):
            TriggerUpdateRequest(**{field: None})


def test_trigger_update_allows_clearing_nullable_fields_and_trims_values() -> None:
    req = TriggerUpdateRequest(
        name="  Weekly report  ",
        prompt_template="  summarize week  ",
        cron_expr="  0 9 * * 1  ",
        timezone="  UTC  ",
        environment_ref="   ",
        description=" ",
    )

    assert req.name == "Weekly report"
    assert req.prompt_template == "summarize week"
    assert req.cron_expr == "0 9 * * 1"
    assert req.timezone == "UTC"
    assert req.environment_ref is None
    assert req.description is None


def test_trigger_requests_reject_removed_system_prompt_field() -> None:
    with pytest.raises(ValidationError):
        TriggerCreateRequest(
            name="Daily report",
            type="cron",
            agent_id=uuid.uuid4(),
            prompt_template="summarize",
            cron_expr="0 9 * * *",
            system_prompt="removed",
        )

    with pytest.raises(ValidationError):
        TriggerUpdateRequest(system_prompt="removed")


def test_trigger_responses_serialize_managed_id_prefixes() -> None:
    trigger_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    trigger = TriggerResponse(
        id=trigger_id,
        name="Daily",
        description=None,
        type="cron",
        agent_id=agent_id,
        prompt_template="summarize",
        environment_ref=None,
        enabled=True,
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
        filter={},
        config={},
        timeout_sec=7200,
        max_retries=2,
        cron_expr="0 9 * * *",
        timezone="UTC",
        concurrency_policy="allow",
        next_run_at=None,
        last_fired_slot=None,
        project_id="project-a",
        last_attempt_at=None,
        last_success_at=None,
        last_error=None,
        consecutive_failures=0,
        last_task_id=task_id,
        last_session_id=None,
        last_payload={},
        created_at=now,
        updated_at=now,
    )
    run = TriggerRunResponse(
        id=task_id,
        trigger_id=trigger_id,
        status="completed",
        retry_count=0,
        max_retries=2,
        chat_session_id=session_id,
        error=None,
        created_at=now,
        started_at=None,
        completed_at=now,
    )

    assert trigger.model_dump(mode="json")["id"] == f"trig_{trigger_id}"
    assert trigger.model_dump(mode="json")["agent_id"] == f"agent_{agent_id}"
    assert trigger.model_dump(mode="json")["last_task_id"] == f"task_{task_id}"
    assert run.model_dump(mode="json")["id"] == f"task_{task_id}"
    assert run.model_dump(mode="json")["trigger_id"] == f"trig_{trigger_id}"
    assert run.model_dump(mode="json")["chat_session_id"] == f"sess_{session_id}"
