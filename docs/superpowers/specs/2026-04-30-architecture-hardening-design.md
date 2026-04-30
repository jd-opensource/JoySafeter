# Architecture Hardening Design

Date: 2026-04-30
Status: Draft for review

## Context

The new architecture has mostly moved the product model to:

```text
Agent -> AgentVersion -> AgentRelease -> AgentRun -> Execution -> ExecutionEvent
```

The remaining risk is not a single broken feature. It is drift between the new domain model and the code/documentation still shaped around the previous graph/run architecture:

- Official architecture docs still mention `GraphService`, `/ws/runs`, SSE execution streams, and top-level Graph APIs.
- `ExecutionOrchestrator` is implemented under `core/engine` even though it performs service-layer orchestration with ORM models, state transitions, event publishing, and credential construction.
- Frontend visual builder code correctly persists through `AgentVersion.definition_payload`, but product-level names still treat `agentId` as `graphId`.
- `definition_kind`, `runtime_kind`, status, trigger source, and event-type values are duplicated across backend models, schemas, state machines, frontend types, and docs.
- Engine capabilities such as message injection, cancellation, debug observation, artifacts, and approvals are implicit instead of discoverable.

This design defines a first hardening phase. The goal is architectural stability and extension readiness, not a cosmetic rename of every historical graph term.

## Goals

1. Make the dependency direction explicit: API/service orchestration depends on core engines, while engines do not own product orchestration.
2. Establish a single canonical contract for kind/status/event values and keep backend, frontend, and docs aligned with it.
3. Make runtime engine capabilities explicit so future engines can be added without hidden UI/API assumptions.
4. Clarify the frontend boundary between product entities (`Agent`, `AgentVersion`) and visual graph implementation details.
5. Update architecture docs so contributors see the current architecture, not the old graph-centric one.
6. Add focused regression coverage for the contracts and boundaries most likely to drift.

## Non-Goals

- Do not redesign the database schema in this phase.
- Do not implement complete code or CLI builder surfaces in this phase.
- Do not rename every internal `graph` variable inside the visual canvas. Graph remains a valid implementation term inside `definition_kind = "graph"`.
- Do not replace the execution event store with a broker or distributed sequence service in this phase unless it is small and low risk during implementation.
- Do not introduce compatibility layers for removed Graph APIs.

## Architecture Direction

### Backend Layering

Move orchestration ownership out of `core/engine`:

```text
api/v1/*
  -> services/dispatch_service.py
  -> services/execution_orchestrator.py
  -> core/engine/registry.py
  -> core/engine/<engine>.py
```

`core/engine` should own:

- `ExecutionEngine` protocol
- `ExecutionContext`
- `EngineRegistry`
- concrete engines such as `GraphEngine`, `CodeEngine`, `CLIEngine`, and `CopilotEngine`
- engine capability metadata

`services/execution_orchestrator.py` should own:

- loading `Agent`, `AgentVersion`, `AgentRelease`, `AgentRun`, `Task`, and `Thread`
- creating `AgentRun` and `Execution`
- dispatching task/chat/direct/draft/debug/copilot flows
- wiring event bus callbacks
- deciding task/run state transitions at the service boundary
- credential construction and runtime-binding selection

The import direction must be one-way: service layer can import engine registry and protocols; engine modules must not import service-layer orchestration.

### Canonical Contracts

Create a backend contract module that is the source for supported values:

```text
backend/app/core/contracts/
  execution.py
  agent.py
```

Initial canonical values:

```text
DefinitionKind = graph | code | claude_code | codex | openclaw
RuntimeKind = graph | code | sandbox
RunStatus = pending | running | succeeded | failed | cancelled
ExecutionStatus = pending | dispatched | running | approval_wait | succeeded | failed | cancelled
ReleaseStatus = ready | active | superseded | failed | retired
TriggerSource = task | chat | api | scheduler | draft_test | draft_copilot | debug | copilot
```

`copilot` is retained for compatibility with existing frontend/API concepts. `draft_copilot` is used for draft-version copilot runs created by the orchestrator. If implementation shows one of these is unused, remove the unused value and update all callers in the same patch.

Backend models may continue using SQLAlchemy enums or strings, but their accepted values must be derived from or tested against the canonical contract. Frontend types must mirror this list exactly.

### Engine Capabilities

Extend the engine abstraction with capability metadata:

```python
@dataclass(frozen=True)
class EngineCapabilities:
    supports_cancel: bool = False
    supports_message_injection: bool = False
    supports_debug_observation: bool = False
    supports_artifacts: bool = False
    supports_approval: bool = False
```

Every engine declares capabilities:

- `CLIEngine`: cancel, message injection if supported by the runtime provider, artifacts, approvals.
- `GraphEngine`: cancel if current task tracking supports it; no message injection until implemented.
- `CodeEngine`: cancel if current task tracking supports it; no message injection unless implemented.
- `CopilotEngine`: cancel if task tracking supports it; no generic message injection.

API message injection should check capabilities before calling `engine.send_message`. Unsupported operations return a structured app error instead of relying on `NotImplementedError`.

### Frontend Boundary

Introduce a thin visual-definition boundary while keeping internal canvas terms stable:

```text
Agent product layer:
  agentId, versionId, workspaceId, definitionKind

Visual definition adapter:
  load/save AgentVersion.definition_payload for definition_kind = graph

Canvas implementation:
  graph nodes, graph edges, graph viewport, graph state fields
```

Rename or wrap product-facing adapters over time:

- `graphDataAdapter` -> `visualDefinitionAdapter`
- `currentGraphId` in shared execution contexts -> `currentDefinitionOwnerId` or `currentAgentId`
- public props should use `agentId` and `versionId`

The first implementation phase should not churn every ReactFlow-internal graph name. It should remove misleading product-boundary names where `graphId` actually means `agentId`.

### Builder Surface Registry

The builder surface registry should be the only product-level dispatch point for definition editing:

```text
definition_kind=graph        -> visual surface
definition_kind=code         -> code surface
definition_kind=claude_code  -> cli surface
definition_kind=codex        -> cli surface
definition_kind=openclaw     -> cli surface
```

In this phase:

- Keep visual surface functional.
- Keep code and CLI surfaces as explicit placeholder surfaces owned by the surface registry.
- Remove hidden product-level code-mode branching from `AgentBuilder`; code-mode routing must happen through the surface registry.
- If extraction requires preserving behavior temporarily, add a named compatibility wrapper with tests and document the exact follow-up file paths.

### Event Sequencing Risk

`PersistenceSubscriber` currently uses an in-memory per-execution sequence cache. That is acceptable only for a single process. In multi-worker or multi-instance deployments, it risks duplicate sequence numbers or ordering drift.

This phase should do one of the following:

1. Preferred if low risk: allocate `sequence_no` atomically in the database.
2. Otherwise: add a clear code comment, document the single-process assumption, and create a follow-up spec for distributed event sequencing.

The implementation should not silently leave this risk undocumented.

## Data Flow

### Task Dispatch

```text
POST /v1/tasks/{task_id}/dispatch
  -> DispatchService.dispatch_task()
  -> ExecutionOrchestrator.dispatch_task()
  -> create AgentRun + Execution
  -> EngineRegistry.get(runtime_kind)
  -> engine.start(context, ...)
  -> context.emit()
  -> execution_event_bus
  -> persistence/state/websocket/task-sync subscribers
```

### Chat Dispatch

```text
POST /v1/threads/{thread_id}/chat
  -> DispatchService.dispatch_chat()
  -> ExecutionOrchestrator.dispatch_chat()
  -> create AgentRun + Execution
  -> emit user_message event
  -> engine events stream through /ws/executions
```

### Draft Test / Copilot

Draft execution binds directly to `AgentVersion` rather than `AgentRelease`. This is valid, but the contract must make it explicit through `AgentRun.agent_version_id` and `trigger_source = draft_test | draft_copilot | debug`.

## Error Handling

- Unsupported engine kind: `EXECUTION_ENGINE_NOT_REGISTERED`.
- Unsupported operation for engine capability: `EXECUTION_OPERATION_UNSUPPORTED`.
- Unsupported definition kind: `AGENT_DEFINITION_KIND_UNSUPPORTED`.
- Invalid status or trigger source: use structured `InvalidRequestError` with the offending value in `data`.
- API routes must not expose raw `NotImplementedError` or unstructured runtime errors for known capability gaps.

## Testing Strategy

### Backend

Add or update focused tests for:

- canonical contract values align with SQLAlchemy model enum values
- `infer_runtime_kind()` maps all supported definition kinds
- `DispatchService` imports and uses service-layer `ExecutionOrchestrator`
- task/chat/direct/draft dispatch create valid `AgentRun` and `Execution` bindings
- `send_message` returns structured unsupported-operation error when engine lacks capability
- event subscriber sequence behavior is documented or atomically handled

### Frontend

Add or update focused tests for:

- frontend `TriggerSource`, `RunStatus`, `ExecutionStatus`, and release status types include backend values
- builder surface registry maps every supported `definition_kind`
- visual definition adapter reads/writes `AgentVersion.definition_payload`
- product-level components pass `agentId/versionId`, not `graphId`, across the surface boundary

### Documentation

Update:

- `docs/ARCHITECTURE.md`
- `docs/ARCHITECTURE_CN.md`
- `docs/architecture-diagram.mmd`

The docs should describe:

- `AgentVersion.definition_payload` absorbing graph definitions
- `/ws/executions` as the real-time execution stream
- `ExecutionOrchestrator` as service-layer orchestration
- engine registry and capabilities
- visual graph as one definition kind, not a top-level product model

## Rollout Plan

1. Contract alignment: add canonical contract module and align frontend/backend types.
2. Orchestrator boundary: move `ExecutionOrchestrator` to service layer and update imports.
3. Engine capability metadata: add capabilities and preflight unsupported operations.
4. Frontend boundary cleanup: introduce visual-definition adapter naming and remove the most misleading `graphId = agentId` surface crossings.
5. Documentation update: refresh architecture docs and diagram.
6. Tests: add regression tests around the changed contracts and boundaries.

Each step should be independently testable and avoid unrelated refactors.

## Acceptance Criteria

- No product-level docs describe `GraphService`, `/ws/runs`, or SSE as the current execution architecture.
- API and scheduler execution paths go through service-layer orchestration.
- `core/engine` contains engine abstractions and engines, not product orchestration.
- Backend and frontend type contracts include the same status, kind, and trigger-source values.
- Unsupported engine operations return structured errors before calling unsupported engine methods.
- Visual builder persists through `AgentVersion.definition_payload` with a product boundary named around agent/version, not graph.
- Tests cover the canonical contracts, dispatch boundary, engine capability handling, and surface registry mapping.

## Risks

- Moving the orchestrator can create import cycles if service modules import too broadly. Keep the move mechanical first, then refine.
- Renaming frontend graph concepts too aggressively can destabilize the visual builder. Only rename product-boundary names in this phase.
- Engine capability declarations may reveal currently unsupported operations that UI still exposes. Prefer disabling or structured errors over fake support.
- Distributed event sequencing may need a second phase if DB-atomic allocation is not small enough for this hardening pass.

## Follow-Up Work

- Complete code builder surface.
- Complete CLI builder surfaces for Claude Code, Codex, and OpenClaw.
- Create distributed-safe execution event sequencing if not implemented in this phase.
- Generate frontend literal types from backend OpenAPI or a shared schema artifact.
- Add architecture lint checks for forbidden dependency directions.
