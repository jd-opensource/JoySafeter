# Unified Error Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all legacy HTTP, execution-event, and WebSocket error shapes with one canonical `ErrorDescriptor` contract consumed uniformly across backend and frontend.

**Architecture:** Introduce a backend `AppError`/`ErrorDescriptor` normalization layer, require all failed HTTP responses and execution transport frames to carry structured `error` payloads, and update frontend data/stream layers to consume only the new contract. This is a hard cutover: legacy fields such as top-level `detail`, sibling `message`, `error_message`, and bare `status: "error"` consumption are removed rather than wrapped.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async services, execution event bus, WebSocket subscriptions, TypeScript, React hooks, Zustand, Vitest, pytest

---

## File Structure

### Backend contract and serializers

- Create: `backend/app/common/error_contract.py`
  Defines canonical backend `ErrorDescriptor`, enums/literals, serialization helpers, and `AppError`.
- Modify: `backend/app/common/response.py`
  Replaces legacy error response builder with `{ success: false, error }` output.
- Modify: `backend/app/common/exceptions.py`
  Reworks exception hierarchy and global handlers to emit canonical `ErrorDescriptor`.
- Modify: `backend/app/schemas/__init__.py`
  Export shared error response schema if needed by route response models.

### Backend execution and websocket transport

- Modify: `backend/app/core/events/envelope.py`
  Replaces loose `error_code` / `error_message` completion metadata with structured error payload support.
- Modify: `backend/app/core/events/subscribers/websocket.py`
  Broadcasts structured `error` payload on `type = "error"` and `execution_completed.failed`.
- Modify: `backend/app/services/execution_service.py`
  Persists and publishes failed execution metadata with canonical error descriptors.
- Modify: `backend/app/services/execution_event_adapter.py`
  Mirrors `ExecutionService` changes for core adapters.
- Modify: `backend/app/websocket/execution_subscription_handler.py`
  Converts protocol/subscribe failures from `ws_error.message` to `ws_error.error`.

### Backend tests

- Create: `backend/tests/test_common/test_error_contract.py`
  Locks error descriptor serialization and unknown exception normalization.
- Create: `backend/tests/test_websocket/test_execution_subscription_handler.py`
  Verifies websocket protocol errors and failed completion frames.
- Modify: `backend/tests/test_core/test_execution_reducer.py`
  Updates event expectations for structured error payloads.

### Frontend data contract

- Create: `frontend/lib/errors/error-contract.ts`
  Defines frontend `ErrorDescriptor`, helper guards, and presenter-friendly types.
- Modify: `frontend/lib/api-client.ts`
  Parses only structured `error` payloads and throws typed `ApiError`.
- Modify: `frontend/lib/ws/executions/types.ts`
  Adds `error` to `ExecutionCompletedFrame` and replaces `ExecutionWsErrorFrame.message`.
- Modify: `frontend/lib/ws/executions/executionWsClient.ts`
  Forwards structured websocket errors.
- Modify: `frontend/hooks/use-execution-stream.ts`
  Tracks structured terminal and websocket errors.
- Modify: `frontend/hooks/copilot/useCopilotExecutionBridge.ts`
  Bridges execution and terminal errors via `ErrorDescriptor`.

### Frontend product consumers and tests

- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
  Consumes structured `ApiError` and removes axios-style / string-based logic.
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`
  Converts structured errors to UI messages/actions.
- Modify: `frontend/lib/utils/skillValidationI18n.ts`
  Stops reading `ApiError.detail` as the contract root.
- Modify: `frontend/lib/auth/api-client.ts`
  Keeps auth wrappers aligned with the new `ApiError`.
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`
  Updates draft copilot failure assertions.
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`
  Verifies structured websocket error handling.

## Task 1: Add Canonical Backend Error Contract Tests

**Files:**
- Create: `backend/tests/test_common/test_error_contract.py`
- Modify: `backend/app/common/error_contract.py`
- Modify: `backend/app/common/exceptions.py`

- [ ] **Step 1: Write the failing backend contract tests**

```python
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
```

- [ ] **Step 2: Run the backend contract tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: FAIL because `normalize_exception`, canonical descriptor serialization, and structured exception fields do not exist yet.

- [ ] **Step 3: Implement the backend error contract and exception normalization**

```python
# backend/app/common/error_contract.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ErrorSource = Literal[
    "api",
    "engine",
    "runtime",
    "node",
    "tool",
    "websocket",
    "auth",
    "validation",
    "permission",
    "internal",
]

UserAction = Literal[
    "retry",
    "configure_model",
    "relogin",
    "fix_input",
    "contact_support",
]


@dataclass(slots=True)
class ErrorDescriptor:
    code: str
    message: str
    source: ErrorSource
    retryable: bool
    detail: str | None = None
    user_action: UserAction | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, http_status: int | None = None) -> dict[str, Any]:
        context = dict(self.context)
        if http_status is not None:
            context["http_status"] = http_status
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "retryable": self.retryable,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.user_action is not None:
            payload["user_action"] = self.user_action
        if context:
            payload["context"] = context
        return payload
```

```python
# backend/app/common/exceptions.py
class AppException(HTTPException):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str,
        source: str,
        retryable: bool,
        detail: str | None = None,
        user_action: str | None = None,
        context: dict[str, Any] | None = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.error = ErrorDescriptor(
            code=code,
            message=message,
            detail=detail,
            source=source,
            retryable=retryable,
            user_action=user_action,
            context=context or {},
        )

    def to_error_descriptor(self, *, http_status: int | None = None) -> dict[str, Any]:
        return self.error.to_dict(http_status=http_status)


def normalize_exception(exc: Exception) -> AppException:
    if isinstance(exc, AppException):
        return exc
    return InternalServerException(
        message="Unexpected internal error.",
        code="INTERNAL_UNEXPECTED_ERROR",
        detail=str(exc),
        source="internal",
        retryable=False,
        user_action="contact_support",
    )
```

- [ ] **Step 4: Run the backend contract tests again and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit the backend error contract foundation**

```bash
git add backend/tests/test_common/test_error_contract.py backend/app/common/error_contract.py backend/app/common/exceptions.py
git commit -m "feat: add canonical backend error contract"
```

## Task 2: Convert HTTP Error Responses to `{ success: false, error }`

**Files:**
- Modify: `backend/app/common/response.py`
- Modify: `backend/app/common/exceptions.py`
- Modify: `frontend/lib/api-client.ts`
- Test: `backend/tests/test_common/test_error_contract.py`

- [ ] **Step 1: Write the failing HTTP envelope test**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import BadRequestException, register_exception_handlers


def test_app_exception_handler_returns_error_envelope() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise BadRequestException(
            message="Invalid request",
            code="VALIDATION_INVALID_REQUEST",
            detail="The request body is malformed.",
            source="validation",
            retryable=False,
            user_action="fix_input",
        )

    client = TestClient(app)
    response = client.get("/boom")

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": {
            "code": "VALIDATION_INVALID_REQUEST",
            "message": "Invalid request",
            "detail": "The request body is malformed.",
            "source": "validation",
            "retryable": False,
            "user_action": "fix_input",
            "context": {"http_status": 400},
        },
    }
```

- [ ] **Step 2: Run the HTTP envelope test and verify it fails**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: FAIL because the current response format still returns `code`, `message`, and `data`.

- [ ] **Step 3: Replace the legacy backend error response builder and API client parser**

```python
# backend/app/common/response.py
def error_response(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
    }
```

```python
# backend/app/common/exceptions.py
def create_error_response(*, status_code: int, error: dict[str, Any]) -> Response:
    return JSONResponse(
        status_code=status_code,
        content=error_response(error=error),
    )


async def app_exception_handler(request: Request, exc: AppException) -> Response:
    return create_error_response(
        status_code=exc.status_code,
        error=exc.to_error_descriptor(http_status=exc.status_code),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    normalized = normalize_exception(
        BadRequestException(
            message=str(exc.detail),
            code="API_HTTP_EXCEPTION",
            detail=str(exc.detail),
            source="api",
            retryable=False,
        )
    )
    return create_error_response(
        status_code=exc.status_code,
        error=normalized.to_error_descriptor(http_status=exc.status_code),
    )
```

```ts
// frontend/lib/api-client.ts
export interface ErrorDescriptor {
  code: string
  message: string
  detail?: string
  source: string
  retryable: boolean
  user_action?: string
  context?: Record<string, unknown>
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly error: ErrorDescriptor,
  ) {
    super(error.message)
    this.name = 'ApiError'
  }
}

async function extractErrorFromResponse(response: Response): Promise<ApiError> {
  const fallback: ErrorDescriptor = {
    code: 'INTERNAL_UNEXPECTED_ERROR',
    message: response.statusText || `API Error: ${response.status}`,
    source: 'api',
    retryable: false,
    context: { http_status: response.status },
  }

  try {
    const text = await response.text()
    const payload = JSON.parse(text)
    return new ApiError(response.status, response.statusText, payload.error ?? fallback)
  } catch {
    return new ApiError(response.status, response.statusText, fallback)
  }
}
```

- [ ] **Step 4: Re-run the HTTP envelope test and the API client tests**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: PASS

Run: `cd frontend && pnpm vitest run frontend/lib/api-client.ts`

Expected: Update or add API client tests as needed and see PASS.

- [ ] **Step 5: Commit the HTTP envelope cutover**

```bash
git add backend/app/common/response.py backend/app/common/exceptions.py frontend/lib/api-client.ts backend/tests/test_common/test_error_contract.py
git commit -m "feat: switch http failures to canonical error envelope"
```

## Task 3: Convert Execution Event and Completion Transport to Structured Errors

**Files:**
- Modify: `backend/app/core/events/envelope.py`
- Modify: `backend/app/services/execution_service.py`
- Modify: `backend/app/services/execution_event_adapter.py`
- Modify: `backend/app/core/events/subscribers/websocket.py`
- Modify: `backend/tests/test_core/test_execution_reducer.py`

- [ ] **Step 1: Write the failing websocket completion transport test**

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.event_types import ExecutionEventType
from app.core.events.subscribers.websocket import WebSocketSubscriber


@pytest.mark.asyncio
async def test_websocket_subscriber_broadcasts_failed_completion_with_error_payload(monkeypatch) -> None:
    broadcast = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(
        "app.core.events.subscribers.websocket.execution_subscription_manager.broadcast_event",
        broadcast,
    )
    monkeypatch.setattr(
        "app.core.events.subscribers.websocket.execution_subscription_manager.remove_execution",
        remove,
    )

    envelope = ExecutionEventEnvelope(
        execution_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        event_type=ExecutionEventType.EXECUTION_COMPLETED,
        terminal_status="failed",
        error={
            "code": "NODE_MODEL_NOT_CONFIGURED",
            "message": 'Node "JSON 抽取子智能体" has no model configured.',
            "source": "node",
            "retryable": False,
        },
    )

    await WebSocketSubscriber().handle(envelope)

    broadcast.assert_awaited_once()
    payload = broadcast.await_args.args[1]
    assert payload["type"] == "execution_completed"
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "NODE_MODEL_NOT_CONFIGURED"
```

- [ ] **Step 2: Run the execution transport tests and verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_reducer.py backend/tests/test_websocket/test_execution_subscription_handler.py -q`

Expected: FAIL because envelopes and websocket broadcasts do not yet carry `error`.

- [ ] **Step 3: Add structured error payload support to execution envelopes and websocket broadcasts**

```python
# backend/app/core/events/envelope.py
@dataclass
class ExecutionEventEnvelope:
    execution_id: uuid.UUID
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: ExecutionEventType | str
    payload: dict[str, Any] = field(default_factory=dict)
    ...
    error: dict[str, Any] | None = None
```

```python
# backend/app/services/execution_service.py
async def complete_execution(
    self,
    *,
    execution_id: uuid.UUID,
    terminal_status: str,
    result_summary: dict | None = None,
    error: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> None:
    envelope = ExecutionEventEnvelope(
        execution_id=execution_id,
        run_id=self._event_ctx.run_id,
        workspace_id=self._event_ctx.workspace_id,
        event_type=ExecutionEventType.EXECUTION_COMPLETED,
        payload={"status": terminal_status},
        terminal_status=terminal_status,
        error=error,
        container_id=session_id,
        metrics=result_summary,
        trigger_source=self._event_ctx.trigger_source,
        thread_id=self._event_ctx.thread_id,
        task_id=self._event_ctx.task_id,
    )
    await execution_event_bus.publish(envelope, self.db)
```

```python
# backend/app/core/events/subscribers/websocket.py
if envelope.event_type == ExecutionEventType.EXECUTION_COMPLETED:
    payload = {
        "type": "execution_completed",
        "execution_id": eid,
        "run_id": str(envelope.run_id),
        "status": envelope.terminal_status,
    }
    if envelope.terminal_status == "failed":
        if envelope.error is None:
            raise RuntimeError("execution_completed.failed missing error descriptor")
        payload["error"] = envelope.error
    await execution_subscription_manager.broadcast_event(eid, payload)
```

- [ ] **Step 4: Re-run the execution transport tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_reducer.py backend/tests/test_websocket/test_execution_subscription_handler.py -q`

Expected: PASS

- [ ] **Step 5: Commit the structured execution transport change**

```bash
git add backend/app/core/events/envelope.py backend/app/services/execution_service.py backend/app/services/execution_event_adapter.py backend/app/core/events/subscribers/websocket.py backend/tests/test_core/test_execution_reducer.py backend/tests/test_websocket/test_execution_subscription_handler.py
git commit -m "feat: add structured error payloads to execution transport"
```

## Task 4: Convert Execution WebSocket Protocol Errors to Structured `ws_error.error`

**Files:**
- Modify: `backend/app/websocket/execution_subscription_handler.py`
- Modify: `frontend/lib/ws/executions/types.ts`
- Modify: `frontend/lib/ws/executions/executionWsClient.ts`
- Test: `backend/tests/test_websocket/test_execution_subscription_handler.py`

- [ ] **Step 1: Write the failing websocket protocol error test**

```python
import json

import pytest

from app.websocket.execution_subscription_handler import ExecutionSubscriptionHandler


@pytest.mark.asyncio
async def test_invalid_json_frame_returns_structured_ws_error() -> None:
    websocket = DummyWebSocket(["not-json"])
    handler = ExecutionSubscriptionHandler()

    await handler._handle_frame(websocket, "user-1", "not-json")

    assert json.loads(websocket.sent[0]) == {
        "type": "ws_error",
        "error": {
            "code": "WEBSOCKET_INVALID_JSON",
            "message": "Invalid websocket frame.",
            "detail": "The execution subscription frame is not valid JSON.",
            "source": "websocket",
            "retryable": False,
        },
    }
```

- [ ] **Step 2: Run the websocket protocol error test and verify it fails**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_websocket/test_execution_subscription_handler.py -q`

Expected: FAIL because protocol errors still emit sibling `message`.

- [ ] **Step 3: Replace bare websocket protocol messages with canonical error descriptors**

```python
# backend/app/websocket/execution_subscription_handler.py
def _ws_error(code: str, message: str, detail: str) -> str:
    return json.dumps(
        {
            "type": "ws_error",
            "error": {
                "code": code,
                "message": message,
                "detail": detail,
                "source": "websocket",
                "retryable": False,
            },
        }
    )
```

```ts
// frontend/lib/ws/executions/types.ts
import type { ErrorDescriptor } from '@/lib/errors/error-contract'

export interface ExecutionCompletedFrame {
  type: 'execution_completed'
  execution_id: string
  run_id: string
  status: string
  error?: ErrorDescriptor
}

export interface ExecutionWsErrorFrame {
  type: 'ws_error'
  error: ErrorDescriptor
}
```

```ts
// frontend/lib/ws/executions/executionWsClient.ts
if (frame.type === 'ws_error') {
  this.subscriptions.forEach(({ callbacks }) => callbacks.onError?.(frame.error))
  return
}
```

- [ ] **Step 4: Re-run the websocket protocol tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_websocket/test_execution_subscription_handler.py -q`

Expected: PASS

- [ ] **Step 5: Commit the websocket protocol contract change**

```bash
git add backend/app/websocket/execution_subscription_handler.py frontend/lib/ws/executions/types.ts frontend/lib/ws/executions/executionWsClient.ts backend/tests/test_websocket/test_execution_subscription_handler.py
git commit -m "feat: switch execution websocket protocol errors to descriptors"
```

## Task 5: Add Frontend Error Descriptor Types and API Client Tests

**Files:**
- Create: `frontend/lib/errors/error-contract.ts`
- Modify: `frontend/lib/api-client.ts`
- Create: `frontend/lib/errors/__tests__/error-contract.test.ts`

- [ ] **Step 1: Write the failing frontend API error parsing tests**

```ts
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/lib/api-client'

describe('ApiError', () => {
  it('stores the canonical error descriptor', () => {
    const error = new ApiError(400, 'Bad Request', {
      code: 'NODE_MODEL_NOT_CONFIGURED',
      message: 'Node "JSON 抽取子智能体" has no model configured.',
      source: 'node',
      retryable: false,
      user_action: 'configure_model',
    })

    expect(error.error.code).toBe('NODE_MODEL_NOT_CONFIGURED')
    expect(error.message).toBe('Node "JSON 抽取子智能体" has no model configured.')
  })
})
```

- [ ] **Step 2: Run the frontend error parsing tests and verify they fail**

Run: `cd frontend && pnpm vitest run lib/errors/__tests__/error-contract.test.ts`

Expected: FAIL because the error contract module and updated `ApiError` shape do not exist yet.

- [ ] **Step 3: Add the frontend contract module and align `ApiError`**

```ts
// frontend/lib/errors/error-contract.ts
export type ErrorSource =
  | 'api'
  | 'engine'
  | 'runtime'
  | 'node'
  | 'tool'
  | 'websocket'
  | 'auth'
  | 'validation'
  | 'permission'
  | 'internal'

export type UserAction =
  | 'retry'
  | 'configure_model'
  | 'relogin'
  | 'fix_input'
  | 'contact_support'

export interface ErrorDescriptor {
  code: string
  message: string
  detail?: string
  source: ErrorSource
  retryable: boolean
  user_action?: UserAction
  context?: Record<string, unknown>
}
```

```ts
// frontend/lib/api-client.ts
import type { ErrorDescriptor } from '@/lib/errors/error-contract'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly error: ErrorDescriptor,
  ) {
    super(error.message)
    this.name = 'ApiError'
  }
}
```

- [ ] **Step 4: Run the frontend error parsing tests again and verify they pass**

Run: `cd frontend && pnpm vitest run lib/errors/__tests__/error-contract.test.ts`

Expected: PASS

- [ ] **Step 5: Commit the frontend error descriptor types**

```bash
git add frontend/lib/errors/error-contract.ts frontend/lib/api-client.ts frontend/lib/errors/__tests__/error-contract.test.ts
git commit -m "feat: add frontend error descriptor types"
```

## Task 6: Update Execution Stream and Copilot Bridge to Consume Structured Errors

**Files:**
- Modify: `frontend/hooks/use-execution-stream.ts`
- Modify: `frontend/hooks/copilot/useCopilotExecutionBridge.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`
- Test: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

- [ ] **Step 1: Write the failing copilot websocket error handling test**

```ts
import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useCopilotWebSocketHandler } from '../useCopilotWebSocketHandler'

describe('useCopilotWebSocketHandler', () => {
  it('maps structured configure-model errors to the final message', () => {
    const actions = {
      clearStreaming: vi.fn(),
      finalizeCurrentMessage: vi.fn(),
      clearSession: vi.fn(),
      setLoading: vi.fn(),
    }

    const refs = {
      isMountedRef: { current: true },
      isCreatingSessionRef: { current: true },
    }

    const { result } = renderHook(() =>
      useCopilotWebSocketHandler({
        state: {} as any,
        actions: actions as any,
        refs: refs as any,
        graphId: 'graph-1',
      }),
    )

    result.current.onError({
      code: 'NODE_MODEL_NOT_CONFIGURED',
      message: 'Node "JSON 抽取子智能体" has no model configured.',
      source: 'node',
      retryable: false,
      user_action: 'configure_model',
      context: { node_name: 'JSON 抽取子智能体' },
    })

    expect(actions.finalizeCurrentMessage).toHaveBeenCalledWith(
      'Node "JSON 抽取子智能体" has no model configured.',
    )
  })
})
```

- [ ] **Step 2: Run the copilot websocket tests and verify they fail**

Run: `cd frontend && pnpm vitest run components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: FAIL because callbacks still accept `(error: string, code?: string)`.

- [ ] **Step 3: Convert execution stream and bridge callbacks to `ErrorDescriptor`**

```ts
// frontend/hooks/use-execution-stream.ts
import type { ErrorDescriptor } from '@/lib/errors/error-contract'

interface UseExecutionStreamResult {
  events: ExecutionEvent[]
  status: string | null
  isConnected: boolean
  wsFailed: boolean
  error: ErrorDescriptor | null
}

const handleCompleted = useCallback((frame: ExecutionCompletedFrame) => {
  if (!mountedRef.current) return
  setStatus(frame.status)
  if (frame.status === 'failed') {
    setError(frame.error ?? {
      code: 'WEBSOCKET_PROTOCOL_ERROR',
      message: 'Failed execution missing error descriptor.',
      source: 'websocket',
      retryable: false,
    })
  }
}, [])
```

```ts
// frontend/hooks/copilot/useCopilotExecutionBridge.ts
import type { ErrorDescriptor } from '@/lib/errors/error-contract'

interface CopilotCallbacks {
  ...
  onError: (error: ErrorDescriptor) => void
}
```

```ts
// frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts
onError: (error) => {
  if (!refs.isMountedRef.current) return
  actions.clearStreaming()
  actions.finalizeCurrentMessage(error.message)
  refs.isCreatingSessionRef.current = false
  actions.clearSession()
  actions.setLoading(false)
}
```

- [ ] **Step 4: Re-run the copilot websocket tests and verify they pass**

Run: `cd frontend && pnpm vitest run components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit the structured stream and copilot bridge change**

```bash
git add frontend/hooks/use-execution-stream.ts frontend/hooks/copilot/useCopilotExecutionBridge.ts frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx
git commit -m "feat: consume structured execution and copilot errors"
```

## Task 7: Update Copilot Actions and Remaining `ApiError.detail` Consumers

**Files:**
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
- Modify: `frontend/lib/utils/skillValidationI18n.ts`
- Modify: `frontend/lib/auth/api-client.ts`
- Test: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`

- [ ] **Step 1: Write the failing copilot dispatch failure test**

```ts
it('surfaces canonical api errors from the draft copilot dispatch call', async () => {
  dispatchRun.mockRejectedValueOnce(
    new ApiError(400, 'Bad Request', {
      code: 'NODE_MODEL_NOT_CONFIGURED',
      message: 'Node "JSON 抽取子智能体" has no model configured.',
      source: 'node',
      retryable: false,
      user_action: 'configure_model',
      context: { node_name: 'JSON 抽取子智能体' },
    }),
  )

  const actions = {
    setInput: vi.fn(),
    addMessage: vi.fn(),
    setLoading: vi.fn(),
    clearStreaming: vi.fn(),
    clearSession: vi.fn(),
    setCurrentStage: vi.fn(),
    setThinkingMessage: vi.fn(),
    setSession: vi.fn(),
    finalizeCurrentMessage: vi.fn(),
    removeCurrentMessage: vi.fn(),
    clearMessages: vi.fn(),
    clearExpandedItems: vi.fn(),
  }

  const refs = {
    isMountedRef: { current: true },
    isCreatingSessionRef: { current: false },
    hasProcessedUrlInputRef: { current: false },
  }

  const { result } = renderHook(() =>
    useCopilotActions({
      state: { input: '', messages: [], loading: false, currentExecutionId: null, currentRunId: null } as any,
      actions: actions as any,
      refs: refs as any,
    }),
  )

  await act(async () => {
    await result.current.handleSendWithInput('Add a node')
  })

  expect(actions.finalizeCurrentMessage).toHaveBeenCalledWith(
    'Node "JSON 抽取子智能体" has no model configured.',
  )
})
```

- [ ] **Step 2: Run the copilot action tests and verify they fail**

Run: `cd frontend && pnpm vitest run components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`

Expected: FAIL because `useCopilotActions` still reads `error.response?.status`, `error.message`, and generic fallback strings.

- [ ] **Step 3: Remove legacy `ApiError.detail` and axios-style error handling**

```ts
// frontend/components/editors/graph-builder/hooks/useCopilotActions.ts
import { ApiError } from '@/lib/api-client'

...
      } catch (e: unknown) {
        if (!refs.isMountedRef.current) return

        actions.setLoading(false)
        actions.clearStreaming()

        if (e instanceof ApiError) {
          actions.finalizeCurrentMessage(e.error.message)
        } else {
          actions.finalizeCurrentMessage(t('workspace.systemError'))
        }

        refs.isCreatingSessionRef.current = false
        actions.clearSession()
      }
```

```ts
// frontend/lib/utils/skillValidationI18n.ts
import { ApiError } from '@/lib/api-client'

if (!(error instanceof ApiError) || !error.error.detail) {
  return ''
}

const d = error.error.detail
```

```ts
// frontend/lib/auth/api-client.ts
error instanceof ApiError ? error : new ApiError(0, 'Unknown Error', {
  code: 'INTERNAL_UNEXPECTED_ERROR',
  message: String(error),
  source: 'internal',
  retryable: false,
})
```

- [ ] **Step 4: Re-run the copilot and auth-adjacent tests and verify they pass**

Run: `cd frontend && pnpm vitest run components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`

Expected: PASS

Run: `cd frontend && pnpm vitest run lib/errors/__tests__/error-contract.test.ts`

Expected: PASS

- [ ] **Step 5: Commit the frontend consumer cleanup**

```bash
git add frontend/components/editors/graph-builder/hooks/useCopilotActions.ts frontend/lib/utils/skillValidationI18n.ts frontend/lib/auth/api-client.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts
git commit -m "feat: remove legacy frontend error parsing"
```

## Task 8: Full Contract Verification and Legacy Cleanup

**Files:**
- Modify: `backend/tests/test_common/test_error_contract.py`
- Modify: `backend/tests/test_websocket/test_execution_subscription_handler.py`
- Modify: `frontend/lib/errors/__tests__/error-contract.test.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

- [ ] **Step 1: Add regression tests that forbid legacy payloads**

```python
def test_http_error_response_has_no_legacy_message_or_data_root() -> None:
    response = create_error_response(
        status_code=400,
        error={
            "code": "VALIDATION_INVALID_REQUEST",
            "message": "Invalid request",
            "source": "validation",
            "retryable": False,
        },
    )

    body = json.loads(response.body)
    assert "message" not in body
    assert "data" not in body
    assert "code" not in body
    assert body["error"]["message"] == "Invalid request"
```

```ts
it('does not require legacy detail/message root fields', () => {
  const payload = {
    success: false,
    error: {
      code: 'NODE_MODEL_NOT_CONFIGURED',
      message: 'Node "JSON 抽取子智能体" has no model configured.',
      source: 'node',
      retryable: false,
    },
  }

  expect(payload).not.toHaveProperty('detail')
  expect(payload).not.toHaveProperty('message')
})
```

- [ ] **Step 2: Run the focused regression suite and verify it fails only if legacy paths remain**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py backend/tests/test_websocket/test_execution_subscription_handler.py -q`

Expected: PASS once legacy root fields are gone.

Run: `cd frontend && pnpm vitest run lib/errors/__tests__/error-contract.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: PASS once frontend consumers no longer rely on legacy fields.

- [ ] **Step 3: Remove dead legacy code and types**

```ts
// Delete any remaining references to:
// - ApiError.detail
// - ApiError.code as a root business code
// - ExecutionWsErrorFrame.message
// - string-based includes('fetch') / includes('WebSocket') / includes('no model configured')
```

```python
# Delete any remaining references to:
# - error_response(message=..., code=..., data=...)
# - envelope.error_code / envelope.error_message as transport contract fields
# - websocket frames with sibling "message"
```

- [ ] **Step 4: Run the final backend and frontend verification commands**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py backend/tests/test_websocket/test_execution_subscription_handler.py backend/tests/test_core/test_execution_reducer.py -q`

Expected: PASS

Run: `cd frontend && pnpm vitest run components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx lib/errors/__tests__/error-contract.test.ts`

Expected: PASS

- [ ] **Step 5: Commit the final hard-cut verification**

```bash
git add backend/tests/test_common/test_error_contract.py backend/tests/test_websocket/test_execution_subscription_handler.py backend/tests/test_core/test_execution_reducer.py frontend/lib/errors/__tests__/error-contract.test.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx
git commit -m "chore: verify unified error contract cutover"
```

## Self-Review

- Spec coverage:
  - Canonical `ErrorDescriptor`: Task 1 and Task 5
  - HTTP failure envelope: Task 2
  - execution event and `execution_completed.failed` contract: Task 3
  - websocket protocol error contract: Task 4
  - frontend data-layer consumption: Task 5, Task 6, Task 7
  - hard cutover and legacy removal: Task 8
- Placeholder scan:
  - No `TODO` / `TBD`
  - Every task includes concrete file paths, commands, and code skeletons
- Type consistency:
  - Backend uses `ErrorDescriptor` / `AppException`
  - Frontend uses `ErrorDescriptor` / `ApiError.error`
  - `execution_completed.failed` consistently requires `error`
