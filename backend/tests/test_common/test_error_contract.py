from __future__ import annotations

from fastapi import status

from app.common.exceptions import BadRequestException, ModelConfigError, normalize_exception


def test_model_config_error_serializes_to_canonical_descriptor() -> None:
    exc = ModelConfigError(
        code="NODE_MODEL_NOT_CONFIGURED",
        message='Node "JSON 抽取子智能体" has no model configured.',
        detail='Node "JSON 抽取子智能体" in agent "a-1" has no model configured.',
        source="node",
        retryable=False,
        user_action="configure_model",
        context={"node_name": "JSON 抽取子智能体", "agent_id": "a-1"},
    )

    payload = exc.to_error_descriptor(http_status=status.HTTP_400_BAD_REQUEST)

    assert payload == {
        "code": "NODE_MODEL_NOT_CONFIGURED",
        "message": 'Node "JSON 抽取子智能体" has no model configured.',
        "detail": 'Node "JSON 抽取子智能体" in agent "a-1" has no model configured.',
        "source": "node",
        "retryable": False,
        "user_action": "configure_model",
        "context": {
            "http_status": 400,
            "node_name": "JSON 抽取子智能体",
            "agent_id": "a-1",
        },
    }


def test_normalize_runtime_error_maps_to_internal_unexpected_error() -> None:
    payload = normalize_exception(RuntimeError("boom")).to_error_descriptor(http_status=500)

    assert payload["code"] == "INTERNAL_UNEXPECTED_ERROR"
    assert payload["source"] == "internal"
    assert payload["retryable"] is False
    assert payload["context"]["http_status"] == 500


def test_bad_request_exception_preserves_structured_fields() -> None:
    exc = BadRequestException(
        message="Invalid request",
        code="VALIDATION_INVALID_REQUEST",
        detail="The request body is malformed.",
        source="validation",
        retryable=False,
        user_action="fix_input",
    )

    payload = exc.to_error_descriptor(http_status=400)

    assert payload["code"] == "VALIDATION_INVALID_REQUEST"
    assert payload["user_action"] == "fix_input"
    assert payload["detail"] == "The request body is malformed."


def test_model_config_error_legacy_error_code_alias_preserves_params_and_descriptor() -> None:
    exc = ModelConfigError(
        error_code="MODEL_NOT_FOUND",
        message='Model "gpt-x" is not registered.',
        params={"model": "gpt-x", "provider": "openai"},
    )

    payload = exc.to_error_descriptor(http_status=400)

    assert exc.error_code == "MODEL_NOT_FOUND"
    assert exc.params == {"model": "gpt-x", "provider": "openai"}
    assert exc.data == {
        "error_code": "MODEL_NOT_FOUND",
        "params": {"model": "gpt-x", "provider": "openai"},
    }
    assert payload["code"] == "MODEL_NOT_FOUND"
    assert payload["context"] == {
        "http_status": 400,
        "model": "gpt-x",
        "provider": "openai",
    }
