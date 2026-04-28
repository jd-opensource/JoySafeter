from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from app.common.app_errors import (
    InternalServiceError,
    InvalidRequestError,
    NotFoundError,
    RequestValidationAppError,
)
from app.common.exceptions import create_error_response
from app.core.agent.code_agent.utils import Retrying
from app.core.engine.registry import EngineRegistry
from app.services.execution_event_adapter import ExecutionEventAdapter
from app.services.execution_reader_adapter import ExecutionReaderAdapter
from app.services.memory_service import MemoryService
from app.services.mcp_client_service import McpClientService


def test_create_error_response_returns_canonical_error_payload() -> None:
    response = create_error_response(
        status_code=404,
        error=NotFoundError(
            "用户不存在",
            code="USER_NOT_FOUND",
            data={"user_id": "user-1"},
        ),
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "code": "USER_NOT_FOUND",
        "message": "用户不存在",
        "data": {"user_id": "user-1"},
    }


def test_create_error_response_preserves_validation_error_data_shape() -> None:
    response = create_error_response(
        status_code=422,
        error=RequestValidationAppError(
            data={
                "errors": [
                    {
                        "field": "body.email",
                        "message": "Field required",
                        "type": "missing",
                    }
                ]
            }
        ),
    )

    assert response.status_code == 422
    assert json.loads(response.body) == {
        "code": "REQUEST_VALIDATION_ERROR",
        "message": "请求参数校验失败",
        "data": {
            "errors": [
                {
                    "field": "body.email",
                    "message": "Field required",
                    "type": "missing",
                }
            ]
        },
    }


def test_engine_registry_raises_structured_error_for_missing_runtime() -> None:
    registry = EngineRegistry()

    try:
        registry.get("graph")
        assert False, "Expected NotFoundError"
    except NotFoundError as exc:
        assert exc.to_payload() == {
            "code": "EXECUTION_ENGINE_NOT_REGISTERED",
            "message": "Execution runtime engine is not registered",
            "data": {
                "runtime_kind": "graph",
                "available_runtime_kinds": "(none)",
            },
        }


def test_mcp_client_requires_server_url_with_structured_error() -> None:
    class Server:
        id = uuid.uuid4()
        name = "missing-url"
        url = None
        transport = "streamable-http"
        timeout = 30000
        headers = {}

    try:
        McpClientService.config_from_server(Server())
        assert False, "Expected InvalidRequestError"
    except InvalidRequestError as exc:
        assert exc.to_payload() == {
            "code": "MCP_SERVER_URL_REQUIRED",
            "message": "Server URL is required",
            "data": {
                "server_id": str(Server.id),
                "name": "missing-url",
            },
        }


def test_execution_event_adapter_requires_context_with_structured_error() -> None:
    adapter = ExecutionEventAdapter(db=None)  # type: ignore[arg-type]

    try:
        import asyncio

        asyncio.run(
            adapter.complete_execution(
                execution_id=uuid.uuid4(),
                terminal_status="failed",
                result_summary=None,
                error=None,
                session_id=None,
            )
        )
        assert False, "Expected InternalServiceError"
    except InternalServiceError as exc:
        assert exc.code == "EXECUTION_EVENT_CONTEXT_MISSING"


def test_execution_reader_adapter_not_found_errors_are_structured() -> None:
    class FakeResult:
        @staticmethod
        def scalar_one_or_none():
            return None

    class FakeDB:
        async def execute(self, *_args, **_kwargs):
            return FakeResult()

    adapter = ExecutionReaderAdapter(FakeDB())  # type: ignore[arg-type]

    try:
        import asyncio

        execution_id = uuid.uuid4()
        asyncio.run(adapter.get_execution(execution_id))
        assert False, "Expected NotFoundError"
    except NotFoundError as exc:
        assert exc.to_payload() == {
            "code": "EXECUTION_NOT_FOUND",
            "message": "Execution not found",
            "data": {"execution_id": str(execution_id)},
        }


def test_memory_service_rejects_unsupported_table_type_with_structured_error() -> None:
    import asyncio

    try:
        asyncio.run(MemoryService()._get_table("invalid"))  # noqa: SLF001
        assert False, "Expected InvalidRequestError"
    except InvalidRequestError as exc:
        assert exc.to_payload() == {
            "code": "MEMORY_TABLE_TYPE_UNSUPPORTED",
            "message": "Unsupported memory table type",
            "data": {"table_type": "invalid"},
        }


def test_mcp_client_requires_initialized_toolkit_session() -> None:
    import asyncio

    class FakeToolkit:
        session = None

    class FakeToolkitManager:
        async def get_toolkit(self, *_args, **_kwargs):
            return FakeToolkit()

    class FakeServer:
        name = "mcp-a"
        user_id = "user-a"

    with patch("app.services.mcp_toolkit_manager.get_toolkit_manager", return_value=FakeToolkitManager()):
        try:
            asyncio.run(
                McpClientService()._fetch_tools(  # noqa: SLF001
                    config=None,  # type: ignore[arg-type]
                    server=FakeServer(),  # type: ignore[arg-type]
                )
            )
            assert False, "Expected InternalServiceError"
        except InternalServiceError as exc:
            assert exc.to_payload() == {
                "code": "MCP_TOOLKIT_SESSION_MISSING",
                "message": "Toolkit session is not initialized",
                "data": {"server_name": "mcp-a"},
            }


def test_retrying_invalid_zero_attempts_raises_structured_internal_error() -> None:
    retrying = Retrying(max_attempts=0)

    try:
        import asyncio

        asyncio.run(retrying(lambda: "ok"))
        assert False, "Expected InternalServiceError"
    except InternalServiceError as exc:
        assert exc.to_payload() == {
            "code": "RETRY_STATE_INVALID",
            "message": "Unexpected state in async retry logic",
            "data": {"mode": "async"},
        }
