# Unified Error Architecture Refactor Design

> Date: 2026-04-27
> Status: Draft
> Scope: Backend exception model, execution/event/websocket/http transport adapters, frontend error consumption
> Supersedes: `docs/superpowers/specs/2026-04-27-unified-error-contract-design.md`

## 1. Problem Statement

The current error work has improved transport consistency, but it is still too transport-driven.

The system still has the deeper structural problem:

- backend business code can still originate failures as ad hoc exceptions
- exception meaning is not yet the single source of truth
- transport layers are still doing some semantic interpretation
- frontend still risks becoming an error inference layer instead of a display layer

This creates a common failure pattern:

1. an error originates as a generic Python exception or transport-oriented exception
2. a later layer wraps or reshapes it
3. the protocol becomes cleaner, but the semantic source remains unstable

That is “doing shells around errors” instead of building a coherent error architecture.

## 2. Design Goal

The system should treat the exception model as the single semantic source of truth.

The architecture target is:

- backend code raises only structured application errors for product-visible failures
- transport layers do not invent error semantics
- execution events, websocket frames, and HTTP responses all serialize the same logical error object
- frontend consumes one error model and never guesses based on strings

This is an architecture refactor, not just a protocol cleanup.

## 3. Core Decision

### 3.1 Rejected Direction

Continue refining transport envelopes first, then clean up backend exception sources later.

This was rejected because it preserves the current inversion of responsibility:

- semantics are weak at the source
- semantics are reconstructed later
- each adapter risks becoming partially responsible for error meaning

### 3.2 Chosen Direction

Refactor around a unified backend exception hierarchy first, then make all transports pure adapters over that hierarchy.

The ordering becomes:

1. unify exception source model
2. replace raw exception usage in services/runtimes
3. adapt HTTP/execution/ws to serialize the model
4. simplify frontend to consume only the resulting model

## 4. Canonical Error Model

The canonical product error payload becomes intentionally small:

```json
{
  "code": "USER_NOT_FOUND",
  "message": "用户不存在",
  "data": null
}
```

If a transport needs an envelope, it wraps that object but does not change its meaning:

```json
{
  "success": false,
  "error": {
    "code": "USER_NOT_FOUND",
    "message": "用户不存在",
    "data": null
  }
}
```

### 4.1 Why This Model

The model is intentionally narrower than the earlier `ErrorDescriptor` draft.

It keeps only:

- `code`: stable programmatic identity
- `message`: default user-facing summary
- `data`: structured diagnostic and UI payload

It avoids placing product semantics in transport-flavored fields such as:

- `source`
- `retryable`
- `user_action`

Those can still be derived or embedded when needed, but they should not be treated as the foundational contract. The real foundation is the exception class and its `code/message/data`.

## 5. Backend Exception Hierarchy

### 5.1 Base Type

All product-visible backend failures should derive from a single base type:

```python
class AppError(Exception):
    code: str
    message: str
    data: dict[str, Any] | None
```

`AppError` is the semantic root. It is not an HTTP exception, not a websocket exception, and not an event-envelope concept.

### 5.2 Exception Families

Use semantic families rather than transport families:

```python
class InfraError(AppError): ...
class DomainError(AppError): ...
class AuthError(AppError): ...
class PermissionDeniedError(AppError): ...
class ValidationError(AppError): ...
class ConflictError(AppError): ...
class RateLimitError(AppError): ...
class InternalError(AppError): ...
```

### 5.3 Concrete Exceptions

Concrete, reusable errors then inherit from those semantic families:

```python
class UserNotFoundError(DomainError): ...
class NodeModelNotConfiguredError(DomainError): ...
class WorkspaceAccessDeniedError(PermissionDeniedError): ...
class ModelCredentialMissingError(InfraError): ...
class OAuthTokenExpiredError(AuthError): ...
```

### 5.4 Architectural Rule

Application code should raise:

- `AppError` subclasses for expected product-visible failures

Application code should not raise directly for product flow:

- `RuntimeError`
- `ValueError`
- `HTTPException`
- stringly-typed “bad request” wrappers

Those generic exceptions are still allowed for truly local/internal code, but they must be translated before crossing an application boundary.

## 6. Layer Responsibilities

### 6.1 Domain / Service / Runtime Layer

This layer owns error meaning.

Responsibilities:

- detect failure conditions
- choose the correct `AppError` subtype
- populate `code`, `message`, and `data`

It must not:

- think about HTTP status codes
- think about websocket frame structure
- think about frontend presentation logic

### 6.2 Transport Adapter Layer

This includes:

- FastAPI exception handlers
- execution event publishers
- websocket subscribers
- reducers/projections if they expose failure state

Responsibilities:

- convert `AppError` to transport payload
- preserve transport metadata such as HTTP status or frame type
- keep the error object unchanged in meaning

It must not:

- invent new error codes
- infer business semantics from raw strings
- maintain parallel error taxonomies

### 6.3 Frontend Data Layer

Responsibilities:

- deserialize transport payload into one frontend error model
- keep that model close to backend shape

Recommended frontend model:

```ts
type FrontendError = {
  code: string
  message: string
  data?: Record<string, unknown> | null
}
```

The frontend client should not be a semantic classifier.

### 6.4 Frontend UI Layer

Responsibilities:

- render by `code`
- optionally inspect `data` for display details or navigation hints

It must not:

- parse strings like `"not found"` or `"fetch"`
- guess retryability
- infer business meaning from transport shape

## 7. Transport Mapping Rules

### 7.1 HTTP

HTTP failure output:

```json
{
  "success": false,
  "error": {
    "code": "USER_NOT_FOUND",
    "message": "用户不存在",
    "data": null
  }
}
```

HTTP status remains transport metadata:

- `404` for `UserNotFoundError`
- `403` for `PermissionDeniedError`
- `422` for `ValidationError`
- `500` for `InternalError`

But the product contract consumed by clients is the `error` object, not the status code.

### 7.2 Execution Events

Execution-related failure events should carry the same `error` object:

```json
{
  "type": "error",
  "error": {
    "code": "NODE_MODEL_NOT_CONFIGURED",
    "message": "节点未配置模型",
    "data": {
      "node_id": "node-1",
      "node_name": "JSON 抽取子智能体"
    }
  }
}
```

### 7.3 Execution Completion Frames

Failed terminal execution frames must carry:

```json
{
  "type": "execution_completed",
  "execution_id": "...",
  "run_id": "...",
  "status": "failed",
  "error": {
    "code": "NODE_MODEL_NOT_CONFIGURED",
    "message": "节点未配置模型",
    "data": {
      "node_id": "node-1",
      "node_name": "JSON 抽取子智能体"
    }
  }
}
```

The transport status says the execution failed; the error object says what failed.

### 7.4 WebSocket Protocol Errors

Protocol-level websocket failures are also serialized through the same error object:

```json
{
  "type": "ws_error",
  "error": {
    "code": "WEBSOCKET_INVALID_JSON",
    "message": "无效的 websocket 帧",
    "data": {
      "detail": "The execution subscription frame is not valid JSON."
    }
  }
}
```

These are still `AppError`-shaped objects, even if their producer is transport infrastructure.

## 8. Refactor Strategy

The previous transport-first plan should be replaced by an exception-model-first refactor sequence.

### Phase 1: Establish the New Exception Model

- introduce `AppError` and semantic subclasses
- define common constructor and serialization helpers
- mark the new model as the only supported semantic error source

### Phase 2: Convert Backend Error Producers

- replace raw `RuntimeError`, `ValueError`, `HTTPException`, and string wrappers in services, orchestrators, execution runners, and runtime adapters
- replace generic “bad request” usage where a more specific domain/infrastructure error exists

This is the most important phase because it eliminates semantic drift at the source.

### Phase 3: Rebuild Transport Adapters Around `AppError`

- HTTP exception handling becomes a thin `AppError -> response` adapter
- execution event publishing becomes `AppError -> event payload`
- websocket broadcasting becomes `AppError -> frame payload`

Existing work on canonical envelopes can be reused here, but only as adapter implementation, not as the system’s semantic foundation.

### Phase 4: Simplify Frontend Error Handling

- collapse frontend HTTP/WS/execution error shapes into one `FrontendError`
- remove transport-specific inference logic
- update UI surfaces to render by `code` and `data`

## 9. Treatment of Existing Work

### Keep

The following work is directionally correct and should be retained:

- backend HTTP canonical envelope
- backend structured error serialization helper work
- execution completion transport work that carries structured errors

### Change in Meaning

These pieces should no longer be treated as the foundation:

- transport-level descriptor design
- frontend-side error classification logic
- adapter-specific metadata as the main contract

### Rewrite

The implementation plan should be rewritten so tasks are organized by exception architecture, not by transport surface.

That means the old sequence:

1. HTTP envelope
2. execution transport
3. websocket protocol
4. frontend consumption

should be replaced with:

1. exception base model
2. backend producer conversion
3. adapter conversion
4. frontend simplification

## 10. Testing Strategy

### Backend

- unit tests for `AppError` base behavior
- unit tests for concrete domain/infrastructure/auth errors
- tests proving services raise specific `AppError` subtypes
- transport adapter tests proving HTTP/event/ws serialize `AppError` without semantic loss

### Frontend

- client tests for HTTP parsing of canonical `error`
- websocket client tests for canonical `error`
- execution bridge tests for failed completion frames
- UI tests that render by `code` and `data`, not by parsed message strings

## 11. Open Decisions Resolved

- **Should we keep refining wrappers first?** No.
- **Should transport layers remain semantically aware?** No.
- **Should frontend keep fallback inference logic?** No.
- **Should the architecture center on backend exception types?** Yes.

## 12. Summary

This refactor changes the center of gravity of the system.

Before:

- semantics weak at the source
- semantics rebuilt at the transport edge
- frontend still at risk of guessing

After:

- `AppError` hierarchy is the single semantic source
- HTTP/execution/websocket are pure adapters
- frontend is a consumer, not an interpreter

That is the more correct architecture for a long-lived error system in this codebase.
