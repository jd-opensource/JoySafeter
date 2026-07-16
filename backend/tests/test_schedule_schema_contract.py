import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleUpdateRequest,
    TriggerResponse,
)

pytestmark = pytest.mark.no_db


def test_schedule_create_trims_strings_before_validation() -> None:
    req = ScheduleCreateRequest(
        name="  Daily report  ",
        agent_id=uuid.uuid4(),
        prompt="  summarize yesterday  ",
        cron_expr="  */5 * * * *  ",
        timezone="  UTC  ",
        concurrency_policy="  forbid  ",
        environment_ref="   ",
        description="  ",
        system_prompt="  be concise  ",
    )

    assert req.name == "Daily report"
    assert req.prompt == "summarize yesterday"
    assert req.cron_expr == "*/5 * * * *"
    assert req.timezone == "UTC"
    assert req.concurrency_policy == "forbid"
    assert req.environment_ref is None
    assert req.description is None
    assert req.system_prompt == "be concise"


def test_schedule_create_rejects_whitespace_only_required_strings() -> None:
    with pytest.raises(ValidationError):
        ScheduleCreateRequest(
            name="   ",
            agent_id=uuid.uuid4(),
            prompt="do work",
            cron_expr="*/5 * * * *",
            timezone="UTC",
        )

    with pytest.raises(ValidationError):
        ScheduleCreateRequest(
            name="Daily report",
            agent_id=uuid.uuid4(),
            prompt="   ",
            cron_expr="*/5 * * * *",
            timezone="UTC",
        )


def test_schedule_update_rejects_explicit_null_for_non_nullable_fields() -> None:
    for field in (
        "name",
        "prompt",
        "cron_expr",
        "timezone",
        "timeout_sec",
        "max_retries",
        "concurrency_policy",
        "enabled",
    ):
        with pytest.raises(ValidationError):
            ScheduleUpdateRequest(**{field: None})


def test_schedule_update_allows_clearing_nullable_fields_and_trims_values() -> None:
    req = ScheduleUpdateRequest(
        name="  Weekly report  ",
        prompt="  summarize week  ",
        cron_expr="  0 9 * * 1  ",
        timezone="  UTC  ",
        environment_ref="   ",
        description=" ",
        system_prompt="  use markdown  ",
    )

    assert req.name == "Weekly report"
    assert req.prompt == "summarize week"
    assert req.cron_expr == "0 9 * * 1"
    assert req.timezone == "UTC"
    assert req.environment_ref is None
    assert req.description is None
    assert req.system_prompt == "use markdown"


def test_schedule_responses_serialize_managed_id_prefixes() -> None:
    schedule_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    schedule = ScheduleResponse(
        id=schedule_id,
        name="Daily",
        description=None,
        agent_id=agent_id,
        prompt="summarize",
        system_prompt=None,
        environment_ref=None,
        cron_expr="0 9 * * *",
        timezone="UTC",
        enabled=True,
        concurrency_policy="allow",
        timeout_sec=7200,
        max_retries=2,
        next_run_at=None,
        last_fired_slot=None,
        project_id="project-a",
        created_at=now,
        updated_at=now,
    )
    run = ScheduleRunResponse(
        id=task_id,
        schedule_id=schedule_id,
        status="completed",
        retry_count=0,
        max_retries=2,
        chat_session_id=session_id,
        error=None,
        created_at=now,
        started_at=None,
        completed_at=now,
    )
    trigger = TriggerResponse(task_id=task_id, session_id=session_id, status="pending")

    assert schedule.model_dump(mode="json")["id"] == f"sched_{schedule_id}"
    assert schedule.model_dump(mode="json")["agent_id"] == f"agent_{agent_id}"
    assert run.model_dump(mode="json")["id"] == f"task_{task_id}"
    assert run.model_dump(mode="json")["schedule_id"] == f"sched_{schedule_id}"
    assert run.model_dump(mode="json")["chat_session_id"] == f"sess_{session_id}"
    assert trigger.model_dump(mode="json")["task_id"] == f"task_{task_id}"
    assert trigger.model_dump(mode="json")["session_id"] == f"sess_{session_id}"
