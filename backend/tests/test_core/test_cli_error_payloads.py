from __future__ import annotations

from app.core.agent.cli_backends.base import CLIMessage
from app.core.agent.cli_backends.execution_runner import _build_completion_error
from app.core.agent.cli_backends.openclaw import OpenClawProvider


def test_cli_message_can_hold_structured_error_payload() -> None:
    message = CLIMessage(
        type="error",
        content="Node has no model configured",
        error_payload={
            "code": "MODEL_NAME_REQUIRED",
            "message": "Node has no model configured",
            "data": {"node": "JSON 抽取子智能体"},
        },
    )

    assert message.error_payload == {
        "code": "MODEL_NAME_REQUIRED",
        "message": "Node has no model configured",
        "data": {"node": "JSON 抽取子智能体"},
    }


def test_openclaw_error_event_emits_canonical_payload() -> None:
    provider = OpenClawProvider()

    messages = provider._parse_event(  # noqa: SLF001
        {
            "type": "error",
            "error": {
                "code": "MODEL_NAME_REQUIRED",
                "message": "Node has no model configured",
                "data": {"node": "JSON 抽取子智能体"},
            },
        }
    )

    assert len(messages) == 1
    assert messages[0].type == "error"
    assert messages[0].content == "Node has no model configured"
    assert messages[0].error_payload == {
        "code": "MODEL_NAME_REQUIRED",
        "message": "Node has no model configured",
        "data": {"node": "JSON 抽取子智能体"},
    }


def test_execution_runner_completion_error_fallback_is_generic() -> None:
    error = _build_completion_error('node "JSON 抽取子智能体" has no model configured')

    assert error == {
        "code": "EXECUTION_FAILED",
        "message": 'node "JSON 抽取子智能体" has no model configured',
        "data": None,
    }


def test_execution_runner_completion_error_fallback_can_drive_error_event_payload() -> None:
    payload = _build_completion_error("Codex agent timed out")

    assert payload == {
        "code": "EXECUTION_FAILED",
        "message": "Codex agent timed out",
        "data": None,
    }
