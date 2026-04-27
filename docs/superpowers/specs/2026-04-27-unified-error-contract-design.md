# Unified Error Contract Design

> Date: 2026-04-27
> Status: Draft
> Scope: Full-stack contract redesign for HTTP APIs, execution events, WebSocket frames, and frontend error consumption

## 1. Problem Statement

The current system does not have a single error contract. Different layers emit different shapes:

- HTTP errors use ad hoc `detail` or `message`
- execution rows store `error_message` and `error_code`
- execution event streams may emit `status: "error"` without structured detail
- WebSocket completion frames only carry terminal status
- frontend code mixes `ApiError`, raw strings, and string matching such as `includes("fetch")`

This creates three failure modes:

1. The backend knows the real failure but the frontend only sees a generic error
2. Synchronous API failures and asynchronous execution failures have different semantics
3. Error handling logic is scattered across string-based heuristics instead of a stable protocol

The result is a system where failures are observable in logs but not reliably actionable in the product UI.

## 2. Goals

### 2.1 Primary Goal

Define one canonical error descriptor for the entire product and require every transport boundary to serialize failures through that descriptor.

### 2.2 Product Goals

- Users always see a precise failure reason instead of a generic system error
- UI recovery flows are driven by structured metadata, not message parsing
- The same failure can be rendered consistently whether it comes from HTTP, execution history, or live WebSocket streaming
- Every failed execution can be traced by a stable `error.code`

### 2.3 Non-Goals

- No backward compatibility layer for old error fields
- No partial migration where some surfaces stay on legacy semantics
- No attempt to normalize arbitrary third-party provider payloads directly to the UI; they must be mapped first

## 3. Design Decision

### 3.1 Rejected Approaches

1. **Patch legacy fields**
   Keep `detail`, `message`, `error_message`, and `status: "error"` while adding helpers around them.
   This was rejected because it preserves multiple contracts and guarantees future divergence.

2. **Unify execution only**
   Clean up execution and WebSocket transport first while leaving ordinary API errors unchanged.
   This was rejected because synchronous and asynchronous failures would still have different consumption models.

### 3.2 Chosen Approach

Adopt a single product-wide error object, `ErrorDescriptor`, and require all failure envelopes to carry it. Every layer may have its own success envelope, but all failure transport must converge on the same error payload.

## 4. Canonical Error Model

### 4.1 ErrorDescriptor

The canonical product error payload is:

```ts
type ErrorSource =
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

type UserAction =
  | 'retry'
  | 'configure_model'
  | 'relogin'
  | 'fix_input'
  | 'contact_support'

type ErrorDescriptor = {
  code: string
  message: string
  detail?: string
  source: ErrorSource
  retryable: boolean
  user_action?: UserAction
  context?: {
    http_status?: number
    run_id?: string
    execution_id?: string
    workspace_id?: string
    agent_id?: string
    node_id?: string
    node_name?: string
    tool_name?: string
    provider_name?: string
  }
}
```

### 4.2 Field Semantics

- `code`: Programmatic primary key. Frontend logic must branch on `code`, never on freeform strings.
- `message`: Default user-visible summary. It must be clear enough to show directly in UI.
- `detail`: Optional expanded diagnostic detail for debug surfaces, logs, or detail drawers.
- `source`: Origin classification used for routing and analytics.
- `retryable`: Whether retry UI should be offered.
- `user_action`: The expected next action if the failure is actionable.
- `context`: Structured identifiers for localization, navigation, and debugging. It must not replace `message`.

### 4.3 Required Invariants

- Every product-visible failure must have an `ErrorDescriptor`
- `code`, `message`, `source`, and `retryable` are mandatory
- If an execution terminates with `status = failed`, its transport payload must include `error`
- Frontend code must not infer semantics by parsing `message`
- Raw exception text must not be emitted to UI without being wrapped into `ErrorDescriptor`

## 5. Transport Contracts

The system has different success envelopes, but failure is serialized through one contract.

### 5.1 HTTP Failure Envelope

All non-2xx business responses must use:

```json
{
  "success": false,
  "error": {
    "code": "NODE_MODEL_NOT_CONFIGURED",
    "message": "Node \"JSON 抽取子智能体\" has no model configured.",
    "detail": "Node \"JSON 抽取子智能体\" in the current agent has no model configured.",
    "source": "node",
    "retryable": false,
    "user_action": "configure_model",
    "context": {
      "http_status": 400,
      "node_name": "JSON 抽取子智能体"
    }
  }
}
```

Implications:

- `detail` is no longer a top-level field
- `message` is no longer the error contract root
- API client code must parse only `error`

### 5.2 WebSocket Error Event

All runtime business failures emitted as live stream events must use:

```json
{
  "type": "error",
  "error": {
    "code": "TOOL_EXECUTION_FAILED",
    "message": "Tool execution failed.",
    "detail": "The tool returned a non-zero exit status.",
    "source": "tool",
    "retryable": true,
    "user_action": "retry",
    "context": {
      "tool_name": "search"
    }
  }
}
```

Implications:

- A frame with `type = "error"` and no `error` object is invalid
- `message` as a sibling of `type` is no longer allowed

### 5.3 Execution Completion Frame

Terminal execution frames must use:

```json
{
  "type": "execution_completed",
  "execution_id": "exec_123",
  "run_id": "run_123",
  "status": "failed",
  "error": {
    "code": "NODE_MODEL_NOT_CONFIGURED",
    "message": "Node \"JSON 抽取子智能体\" has no model configured.",
    "detail": "Node \"JSON 抽取子智能体\" in the current agent has no model configured.",
    "source": "node",
    "retryable": false,
    "user_action": "configure_model",
    "context": {
      "node_name": "JSON 抽取子智能体",
      "execution_id": "exec_123",
      "run_id": "run_123"
    }
  }
}
```

Rules:

- `status = failed` requires `error`
- `status = succeeded` and `status = cancelled` must not carry a business failure descriptor
- Consumers must treat `failed` without `error` as a protocol violation

### 5.4 Persistence Model

Execution persistence may keep normalized columns such as `error_code` and `error_message`, but those are persistence concerns, not the external contract. Transport payloads must always rebuild a full `ErrorDescriptor`.

## 6. Error Taxonomy

Error codes must be explicit and namespaced. The initial taxonomy is:

- `AUTH_*`
- `VALIDATION_*`
- `PERMISSION_*`
- `MODEL_*`
- `NODE_*`
- `TOOL_*`
- `ENGINE_*`
- `RUNTIME_*`
- `WEBSOCKET_*`
- `INTERNAL_*`

Examples:

- `AUTH_SESSION_EXPIRED`
- `MODEL_CREDENTIALS_MISSING`
- `NODE_MODEL_NOT_CONFIGURED`
- `TOOL_EXECUTION_FAILED`
- `ENGINE_DISPATCH_FAILED`
- `WEBSOCKET_PROTOCOL_ERROR`
- `INTERNAL_UNEXPECTED_ERROR`

Constraints:

- `code` values are part of the product contract and must be documented
- `message` may evolve for wording clarity, but `code` stability matters more
- Multiple raw exceptions may map to the same product code when they imply the same user action

## 7. Backend Responsibilities

### 7.1 Domain and Engine Layers

Backend business logic must throw structured application errors, not plain strings.

Recommended base shape:

```python
class AppError(Exception):
    code: str
    message: str
    detail: str | None
    source: ErrorSource
    retryable: bool
    user_action: UserAction | None
    context: dict[str, Any]
```

Rules:

- Domain and engine code define the semantic error
- Transport layers do not invent semantics after the fact
- Unknown exceptions are mapped once at the boundary to `INTERNAL_UNEXPECTED_ERROR`

### 7.2 API and WebSocket Adapters

Adapters are serialization boundaries only.

- FastAPI handlers serialize `AppError` into HTTP failure envelopes
- WebSocket subscribers serialize `AppError` into event frames or terminal frames
- Event bus publishers must attach error descriptors to failed terminal events

Adapters must not:

- invent ad hoc `detail` fields
- emit freeform sibling `message` fields
- switch on UI copy

### 7.3 Execution and Event Pipeline

Execution flow must enforce:

- `execution_completed.failed` always includes `error`
- intermediate `type = error` events always include `error`
- stored execution error metadata is sufficient to reconstruct the canonical descriptor for history and replay

The execution event envelope should therefore evolve from string metadata to structured error metadata rather than only carrying `error_code` and `error_message`.

## 8. Frontend Responsibilities

### 8.1 Data Layer

Frontend transport code must normalize all failures into one client-side shape, for example `AppErrorDescriptor`, which is isomorphic to the backend `ErrorDescriptor`.

Required changes:

- `api-client` parses only `response.error`
- WebSocket clients parse only `frame.error`
- execution stream hooks expose structured errors instead of generic status-only failures
- copilot bridges and execution stores consume standardized errors only

### 8.2 UI Layer

UI decisions may use:

- `error.code`
- `error.retryable`
- `error.user_action`
- `error.context`

UI decisions must not use:

- string inclusion checks such as `includes("fetch")`
- raw `statusText`
- ad hoc branching on translated copy

### 8.3 Error Presentation

The frontend should provide a single presenter or mapper for common actions:

- `configure_model`: open or deep-link to model configuration
- `relogin`: prompt login refresh
- `retry`: surface retry CTA
- `fix_input`: focus relevant form or node configuration
- `contact_support`: show escalation path

This keeps the contract semantic while leaving visual treatment in product-specific surfaces.

## 9. Hard Cutover Strategy

This redesign is a hard cutover. No compatibility layer will be retained.

### 9.1 Migration Order

1. Introduce canonical backend error types and serializer utilities
2. Convert all HTTP error responses to the new envelope
3. Convert execution events, WebSocket error frames, and terminal frames
4. Update frontend API and WebSocket data layers to only consume the new contract
5. Update product surfaces and hooks to remove all legacy parsing
6. Delete old types, fields, and tests that depend on legacy contracts

### 9.2 Hard Rules During Migration

- Backend and frontend changes must land together
- No new code may depend on `detail`, `message`, or `error_message` as root error fields
- Any failed execution without `error` blocks release
- Any frontend string-matching fallback blocks release

## 10. Validation and Testing

The redesign is not complete until the contract is enforced by tests.

### 10.1 Backend Tests

- unit tests for `AppError -> ErrorDescriptor`
- unit tests for unknown exception normalization
- API contract tests for HTTP failure envelopes
- event and WebSocket contract tests for `type = error` and `execution_completed.failed`

### 10.2 Frontend Tests

- API client tests for `error` parsing
- WebSocket client tests for `frame.error`
- execution bridge tests for failed terminal frames with structured error payloads
- copilot and graph-builder tests proving node/model configuration failures surface the node name and action

### 10.3 End-to-End Acceptance

Representative failures must pass through the full stack:

- missing model configuration
- invalid input
- authentication expiration
- runtime/tool failure

Success criteria:

- the UI shows a precise user-facing error
- the same `error.code` is visible across logs, execution history, and live failure UI
- no product surface degrades a structured error into a generic system message

## 11. Open Questions Resolved

- **Compatibility fallback:** rejected
- **Partial scope limited to execution:** rejected
- **Legacy field preservation in frontend or backend:** rejected

The system will move to a single contract and delete legacy error semantics rather than layering over them.
