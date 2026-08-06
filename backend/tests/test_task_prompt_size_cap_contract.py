"""Task prompt/system fields must be length-bounded at the schema layer.

The body-size middleware is a coarse per-worker OOM guard (64 MiB). It cannot
finely bound a single text field: an ~60 MiB `prompt` still sails through, then
lands in a DB row and is fanned out over Redis pub/sub to every SSE subscriber
(N-way amplification). A per-field cap gives a clean 422 well below the body cap
and bounds the row + fan-out cost of one submission.
"""

import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_task import (
    MAX_PROMPT_CHARS,
    JoySafeterCreateTaskRequest,
    JoySafeterCreateTaskResponse,
    JoySafeterTaskResponse,
)

pytestmark = pytest.mark.no_db


def test_prompt_at_cap_is_accepted():
    req = JoySafeterCreateTaskRequest(prompt="x" * MAX_PROMPT_CHARS)
    assert len(req.prompt) == MAX_PROMPT_CHARS


def test_prompt_over_cap_is_rejected():
    with pytest.raises(ValidationError):
        JoySafeterCreateTaskRequest(prompt="x" * (MAX_PROMPT_CHARS + 1))


def test_system_over_cap_is_rejected():
    with pytest.raises(ValidationError):
        JoySafeterCreateTaskRequest(prompt="ok", system="x" * (MAX_PROMPT_CHARS + 1))


def test_normal_prompt_is_unaffected():
    req = JoySafeterCreateTaskRequest(prompt="scan the target host", system="you are a pentest agent")
    assert req.prompt == "scan the target host"
    assert req.system == "you are a pentest agent"


def test_removed_system_prompt_field_is_rejected():
    with pytest.raises(ValidationError):
        JoySafeterCreateTaskRequest(prompt="ok", system_prompt="old field")


def test_task_response_serializes_internal_system_prompt_as_system():
    response = JoySafeterTaskResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "agent_id": "00000000-0000-0000-0000-000000000002",
            "status": "pending",
            "prompt": "scan",
            "system_prompt": "be precise",
            "timeout_sec": 60,
            "retry_count": 0,
            "max_retries": 0,
            "created_at": "2026-08-05T00:00:00Z",
        }
    )

    payload = response.model_dump()
    assert payload["system"] == "be precise"
    assert "system_prompt" not in payload


def test_task_responses_use_canonical_prefixed_ids():
    task_id = "00000000-0000-0000-0000-000000000001"
    agent_id = "00000000-0000-0000-0000-000000000002"
    session_id = "00000000-0000-0000-0000-000000000003"
    sandbox_id = "00000000-0000-0000-0000-000000000004"

    created = JoySafeterCreateTaskResponse(id=task_id, status="pending").model_dump(mode="json")
    task = JoySafeterTaskResponse.model_validate(
        {
            "id": task_id,
            "agent_id": agent_id,
            "chat_session_id": session_id,
            "status": "pending",
            "prompt": "scan",
            "sandbox_id": sandbox_id,
            "timeout_sec": 60,
            "retry_count": 0,
            "max_retries": 0,
            "created_at": "2026-08-06T00:00:00Z",
        }
    ).model_dump(mode="json")

    assert created["id"] == f"task_{task_id}"
    assert task["id"] == f"task_{task_id}"
    assert task["agent_id"] == f"agent_{agent_id}"
    assert task["chat_session_id"] == f"sess_{session_id}"
    assert task["sandbox_id"] == f"sbx_{sandbox_id}"
