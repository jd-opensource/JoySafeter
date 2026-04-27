# Unified Error Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the product error system around a single backend `AppError` hierarchy, then rewire HTTP, execution events, websocket frames, and frontend consumption to serialize and consume that model without compatibility fallbacks.

**Architecture:** This refactor is exception-model-first, not transport-first. Backend services, orchestrators, runtimes, and infrastructure adapters must raise structured `AppError` subtypes as the single semantic source of truth; HTTP/execution/websocket layers become pure serializers; frontend data clients consume one unified error object. The refactor must be completed continuously without leaving mixed old/new paths behind, and must not add any compatibility fallback, legacy parsing, or rollback branch for workflow convenience.

**Tech Stack:** Python exceptions, FastAPI, Pydantic, SQLAlchemy async services, execution event bus, websocket subscriptions, TypeScript, React, Zustand, Vitest, pytest

---

## Non-Negotiable Constraints

- No compatibility fallback for legacy error shapes
- No parallel old/new error pipelines left active after a task completes
- No string-based error inference in frontend or backend adapters
- No transport layer inventing business semantics
- No “temporary” rollback branch because of workflow pressure

If a task cannot be completed without preserving old behavior, the task must expand to finish the migration, not defer the cleanup.

## File Structure

### Backend exception model

- Create: `backend/app/common/app_errors.py`
  Defines `AppError`, semantic families, concrete base helpers, and serializer methods.
- Modify: `backend/app/common/exceptions.py`
  Retire transport-shaped exception semantics and turn this module into adapter glue over `AppError`.
- Modify: `backend/app/common/response.py`
  Serialize only canonical `error = { code, message, data }`.

### Backend producer migration

- Modify: `backend/app/services/model_service.py`
- Modify: `backend/app/services/copilot_service.py`
- Modify: `backend/app/core/engine/orchestrator.py`
- Modify: `backend/app/core/graph/deep_agents/model_resolver.py`
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py`
- Modify: `backend/app/services/execution_service.py`
- Modify: `backend/app/services/execution_event_adapter.py`
- Modify: `backend/app/core/ports/execution.py`

These files cover the current high-signal producers of configuration, runtime, and execution errors that already surfaced during the transport work.

### Backend transport adapters

- Modify: `backend/app/core/events/envelope.py`
- Modify: `backend/app/core/events/subscribers/websocket.py`
- Modify: `backend/app/websocket/execution_subscription_handler.py`

### Frontend data layer

- Create: `frontend/lib/errors/app-error.ts`
  Unified frontend error model matching backend `{ code, message, data }`.
- Modify: `frontend/lib/api-client.ts`
- Modify: `frontend/lib/ws/executions/types.ts`
- Modify: `frontend/lib/ws/executions/executionWsClient.ts`
- Modify: `frontend/hooks/use-execution-stream.ts`
- Modify: `frontend/hooks/copilot/useCopilotExecutionBridge.ts`

### Frontend consumers

- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`
- Modify: `frontend/lib/utils/skillValidationI18n.ts`
- Modify: `frontend/lib/auth/api-client.ts`

### Tests

- Create: `backend/tests/test_common/test_app_errors.py`
- Modify: `backend/tests/test_common/test_error_contract.py`
- Modify: `backend/tests/test_core/test_execution_subscription.py`
- Modify: `backend/tests/test_core/test_execution_reducer.py`
- Create: `frontend/lib/errors/__tests__/app-error.test.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

## Task 1: Establish the `AppError` Core Model

**Files:**
- Create: `backend/app/common/app_errors.py`
- Modify: `backend/tests/test_common/test_app_errors.py`
- Modify: `backend/app/common/exceptions.py`

- [ ] **Step 1: Write the failing backend exception model tests**

```python
from app.common.app_errors import (
    AppError,
    DomainError,
    InfraError,
    ValidationError,
    PermissionDeniedError,
)


def test_app_error_serializes_to_canonical_payload() -> None:
    err = AppError(
        code="USER_NOT_FOUND",
        message="用户不存在",
        data={"user_id": "u-1"},
    )

    assert err.to_payload() == {
        "code": "USER_NOT_FOUND",
        "message": "用户不存在",
        "data": {"user_id": "u-1"},
    }


def test_domain_error_is_an_app_error() -> None:
    err = DomainError(
        code="NODE_MODEL_NOT_CONFIGURED",
        message="节点未配置模型",
        data={"node_id": "node-1"},
    )

    assert isinstance(err, AppError)
    assert err.code == "NODE_MODEL_NOT_CONFIGURED"


def test_validation_error_keeps_structured_data() -> None:
    err = ValidationError(
        code="REQUEST_INVALID",
        message="请求参数校验失败",
        data={"field": "workspace_id"},
    )

    assert err.to_payload()["data"] == {"field": "workspace_id"}
```

- [ ] **Step 2: Run the exception model tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py -q`

Expected: FAIL because `app_errors.py` and `to_payload()` do not exist yet.

- [ ] **Step 3: Implement the canonical backend exception hierarchy**

```python
# backend/app/common/app_errors.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    data: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
        }


class InfraError(AppError):
    pass


class DomainError(AppError):
    pass


class AuthError(AppError):
    pass


class PermissionDeniedError(AppError):
    pass


class ValidationError(AppError):
    pass


class ConflictError(AppError):
    pass


class RateLimitError(AppError):
    pass


class InternalError(AppError):
    pass
```

```python
# backend/app/common/exceptions.py
from app.common.app_errors import (
    AppError,
    AuthError,
    ConflictError,
    InternalError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)
```

- [ ] **Step 4: Run the exception model tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py -q`

Expected: PASS

- [ ] **Step 5: Commit the exception core model**

```bash
git add backend/app/common/app_errors.py backend/tests/test_common/test_app_errors.py backend/app/common/exceptions.py
git commit -m "feat: add canonical app error hierarchy"
```

## Task 2: Rebuild HTTP Exception Handling Around `AppError`

**Files:**
- Modify: `backend/app/common/exceptions.py`
- Modify: `backend/app/common/response.py`
- Modify: `backend/tests/test_common/test_error_contract.py`

- [ ] **Step 1: Write the failing HTTP adapter tests for `AppError`**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.app_errors import DomainError
from app.common.exceptions import register_exception_handlers


def test_domain_error_becomes_canonical_http_error() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise DomainError(
            code="USER_NOT_FOUND",
            message="用户不存在",
            data={"user_id": "u-1"},
        )

    client = TestClient(app)
    response = client.get("/boom")

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": {
            "code": "USER_NOT_FOUND",
            "message": "用户不存在",
            "data": {"user_id": "u-1"},
        },
    }
```

- [ ] **Step 2: Run the HTTP adapter tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: FAIL because handlers still depend on transport-shaped exception logic.

- [ ] **Step 3: Replace transport-shaped exception adaptation with pure `AppError` mapping**

```python
# backend/app/common/response.py
def error_response(error: dict[str, Any]) -> dict:
    return {
        "success": False,
        "error": error,
    }
```

```python
# backend/app/common/exceptions.py
def create_error_response(*, status_code: int, error: AppError, headers: Mapping[str, str] | None = None) -> Response:
    return JSONResponse(
        status_code=status_code,
        content=error_response(error=error.to_payload()),
        headers=dict(headers) if headers else None,
    )
```

- [ ] **Step 4: Run the HTTP adapter tests again and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_error_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit the HTTP adapter refactor**

```bash
git add backend/app/common/exceptions.py backend/app/common/response.py backend/tests/test_common/test_error_contract.py
git commit -m "feat: adapt http errors from app error model"
```

## Task 3: Replace Raw Error Producers in Model/Copilot/Graph Paths

**Files:**
- Modify: `backend/app/services/model_service.py`
- Modify: `backend/app/services/copilot_service.py`
- Modify: `backend/app/core/graph/deep_agents/model_resolver.py`
- Modify: `backend/app/tests/test_common/test_app_errors.py`

- [ ] **Step 1: Write failing tests for concrete domain/infra errors**

```python
from app.common.app_errors import DomainError, InfraError
from app.core.graph.deep_agents.model_resolver import resolve_model


def test_model_resolver_raises_domain_error_for_missing_node_model():
    with pytest.raises(DomainError) as exc_info:
        resolve_model(...)

    assert exc_info.value.code == "NODE_MODEL_NOT_CONFIGURED"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py backend/tests/test_services/test_copilot_service.py -q`

Expected: FAIL because these paths still raise old exception types.

- [ ] **Step 3: Convert model/configuration producers to `AppError` subclasses**

```python
class NodeModelNotConfiguredError(DomainError):
    def __init__(self, *, node_id: str | None, node_name: str | None):
        super().__init__(
            code="NODE_MODEL_NOT_CONFIGURED",
            message="节点未配置模型",
            data={"node_id": node_id, "node_name": node_name},
        )
```

- [ ] **Step 4: Re-run the focused producer tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py backend/tests/test_services/test_copilot_service.py -q`

Expected: PASS

- [ ] **Step 5: Commit the producer conversion**

```bash
git add backend/app/services/model_service.py backend/app/services/copilot_service.py backend/app/core/graph/deep_agents/model_resolver.py backend/tests/test_common/test_app_errors.py
git commit -m "feat: convert model and copilot producers to app errors"
```

## Task 4: Convert Execution Failure Producers to `AppError`

**Files:**
- Modify: `backend/app/core/engine/orchestrator.py`
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py`
- Modify: `backend/app/core/ports/execution.py`
- Modify: `backend/app/services/execution_service.py`
- Modify: `backend/app/services/execution_event_adapter.py`

- [ ] **Step 1: Write the failing execution failure tests**

```python
async def test_complete_execution_failed_requires_app_error_payload(...) -> None:
    ...
    await service.complete_execution(
        execution_id=execution_id,
        terminal_status="failed",
        error=InternalError(code="EXECUTION_FAILED", message="执行失败"),
    )
```

- [ ] **Step 2: Run the execution failure tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_subscription.py -q`

Expected: FAIL because execution completion still mixes legacy `error_code` / `error_message` semantics.

- [ ] **Step 3: Convert execution producers and adapters to carry `AppError` payloads**

```python
# complete_execution(...) should accept `error: AppError | None`
# event envelopes should serialize `error.to_payload()`
```

- [ ] **Step 4: Re-run the execution tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_subscription.py -q`

Expected: PASS

- [ ] **Step 5: Commit the execution producer refactor**

```bash
git add backend/app/core/engine/orchestrator.py backend/app/core/agent/cli_backends/execution_runner.py backend/app/core/ports/execution.py backend/app/services/execution_service.py backend/app/services/execution_event_adapter.py
git commit -m "feat: convert execution producers to app errors"
```

## Task 5: Rebuild Execution Event and WebSocket Adapters

**Files:**
- Modify: `backend/app/core/events/envelope.py`
- Modify: `backend/app/core/events/subscribers/websocket.py`
- Modify: `backend/app/websocket/execution_subscription_handler.py`
- Modify: `backend/tests/test_core/test_execution_subscription.py`
- Modify: `backend/tests/test_core/test_execution_reducer.py`

- [ ] **Step 1: Write the failing adapter tests for canonical execution/websocket errors**

```python
def test_failed_execution_completed_frame_contains_canonical_error_payload():
    ...
    assert payload["error"] == {
        "code": "NODE_MODEL_NOT_CONFIGURED",
        "message": "节点未配置模型",
        "data": {"node_id": "node-1"},
    }
```

- [ ] **Step 2: Run the adapter tests to verify they fail**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_subscription.py backend/tests/test_core/test_execution_reducer.py -q`

Expected: FAIL because adapters still carry legacy event fields and protocol-specific error semantics.

- [ ] **Step 3: Convert event/websocket adapters to pure `AppError` serialization**

```python
# failed execution frames and ws_error frames must carry:
# {"code": ..., "message": ..., "data": ...}
```

- [ ] **Step 4: Re-run the adapter tests and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_subscription.py backend/tests/test_core/test_execution_reducer.py -q`

Expected: PASS

- [ ] **Step 5: Commit the adapter refactor**

```bash
git add backend/app/core/events/envelope.py backend/app/core/events/subscribers/websocket.py backend/app/websocket/execution_subscription_handler.py backend/tests/test_core/test_execution_subscription.py backend/tests/test_core/test_execution_reducer.py
git commit -m "feat: adapt execution and websocket errors from app errors"
```

## Task 6: Create a Unified Frontend Error Model

**Files:**
- Create: `frontend/lib/errors/app-error.ts`
- Modify: `frontend/lib/api-client.ts`
- Create: `frontend/lib/errors/__tests__/app-error.test.ts`

- [ ] **Step 1: Write the failing frontend error model tests**

```ts
import { describe, expect, it } from 'vitest'
import { toFrontendError } from '@/lib/errors/app-error'

describe('toFrontendError', () => {
  it('maps canonical backend payload directly', () => {
    expect(
      toFrontendError({
        code: 'USER_NOT_FOUND',
        message: '用户不存在',
        data: { user_id: 'u-1' },
      }),
    ).toEqual({
      code: 'USER_NOT_FOUND',
      message: '用户不存在',
      data: { user_id: 'u-1' },
    })
  })
})
```

- [ ] **Step 2: Run the frontend error model tests to verify they fail**

Run: `cd frontend && bun run vitest run lib/errors/__tests__/app-error.test.ts`

Expected: FAIL because the unified frontend error model does not exist yet.

- [ ] **Step 3: Implement the unified frontend error model and simplify `api-client`**

```ts
export type FrontendError = {
  code: string
  message: string
  data?: Record<string, unknown> | null
}
```

- [ ] **Step 4: Re-run the frontend error model tests and verify they pass**

Run: `cd frontend && bun run vitest run lib/errors/__tests__/app-error.test.ts`

Expected: PASS

- [ ] **Step 5: Commit the frontend error model**

```bash
git add frontend/lib/errors/app-error.ts frontend/lib/api-client.ts frontend/lib/errors/__tests__/app-error.test.ts
git commit -m "feat: add unified frontend error model"
```

## Task 7: Rewire Frontend Execution and Copilot Error Consumption

**Files:**
- Modify: `frontend/lib/ws/executions/types.ts`
- Modify: `frontend/lib/ws/executions/executionWsClient.ts`
- Modify: `frontend/hooks/use-execution-stream.ts`
- Modify: `frontend/hooks/copilot/useCopilotExecutionBridge.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`
- Modify: `frontend/lib/utils/skillValidationI18n.ts`
- Modify: `frontend/lib/auth/api-client.ts`

- [ ] **Step 1: Write the failing frontend consumer tests**

```ts
it('surfaces canonical execution error payloads without string parsing', () => {
  ...
  expect(error.code).toBe('NODE_MODEL_NOT_CONFIGURED')
})
```

- [ ] **Step 2: Run the frontend consumer tests to verify they fail**

Run: `cd frontend && bun run vitest run components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: FAIL because consumers still depend on transport-specific shapes.

- [ ] **Step 3: Rewire all frontend consumers to the canonical `FrontendError`**

```ts
// remove old descriptor/detail/code duplication
// remove string matching
// consume only { code, message, data }
```

- [ ] **Step 4: Re-run the frontend consumer tests and verify they pass**

Run: `cd frontend && bun run vitest run components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit the frontend consumer refactor**

```bash
git add frontend/lib/ws/executions/types.ts frontend/lib/ws/executions/executionWsClient.ts frontend/hooks/use-execution-stream.ts frontend/hooks/copilot/useCopilotExecutionBridge.ts frontend/components/editors/graph-builder/hooks/useCopilotActions.ts frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts frontend/lib/utils/skillValidationI18n.ts frontend/lib/auth/api-client.ts
git commit -m "feat: rewire frontend consumers to unified app errors"
```

## Task 8: Remove Legacy Error Mechanisms Completely

**Files:**
- Modify: `backend/app/common/exceptions.py`
- Modify: `backend/app/core/events/envelope.py`
- Modify: `backend/app/services/execution_service.py`
- Modify: `backend/app/services/execution_event_adapter.py`
- Modify: `frontend/lib/api-client.ts`
- Modify: `frontend/lib/ws/executions/types.ts`

- [ ] **Step 1: Write regression tests that forbid legacy error mechanisms**

```python
def test_no_legacy_error_message_or_error_code_fields_remain():
    ...
```

```ts
it('does not expose legacy descriptor/detail compatibility fields', () => {
  ...
})
```

- [ ] **Step 2: Run the regression tests to verify they fail while legacy fields remain**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py backend/tests/test_core/test_execution_subscription.py -q`

Expected: FAIL until legacy mechanisms are removed.

- [ ] **Step 3: Delete legacy mechanisms**

```python
# remove old transport-shaped exception helpers
# remove error_code / error_message fields as semantic carriers
```

```ts
// remove ApiError descriptor/detail duplication
// keep one frontend error shape only
```

- [ ] **Step 4: Run final backend and frontend verification**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_common/test_app_errors.py backend/tests/test_common/test_error_contract.py backend/tests/test_core/test_execution_subscription.py backend/tests/test_core/test_execution_reducer.py backend/tests/test_services/test_copilot_service.py -q`

Expected: PASS

Run: `cd frontend && bun run type-check`

Expected: PASS

Run: `cd frontend && bun run vitest run lib/errors/__tests__/app-error.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts components/editors/graph-builder/hooks/__tests__/useCopilotWebSocketHandler.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit the legacy removal cutover**

```bash
git add backend/app/common/exceptions.py backend/app/core/events/envelope.py backend/app/services/execution_service.py backend/app/services/execution_event_adapter.py frontend/lib/api-client.ts frontend/lib/ws/executions/types.ts
git commit -m "chore: remove legacy error mechanisms"
```

## Self-Review

- Spec coverage:
  - backend exception hierarchy: Task 1
  - HTTP adapter rewrite: Task 2
  - backend producer conversion: Task 3 and Task 4
  - execution/event/ws adapters: Task 5
  - frontend unified model and consumer simplification: Task 6 and Task 7
  - complete legacy removal with no fallback: Task 8
- Placeholder scan:
  - No `TODO` / `TBD`
  - Each task contains explicit files, commands, and code shapes
- Type consistency:
  - backend root type is always `AppError`
  - transport payload is always `{ code, message, data }`
  - frontend root type is always `FrontendError`
