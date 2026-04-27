# Draft Copilot Boundary Design

Date: 2026-04-27
Status: Design

## Context

Visual Agent Studio currently sends Build-stage Copilot requests through a release-based execution path:

```text
Graph Builder Copilot
  -> POST /v1/copilot/run
  -> dispatch_copilot()
  -> requires agent.active_release_id
```

This creates a product and architecture mismatch:

- Build-stage Copilot is blocked when an Agent has no active release.
- The error message tells users to publish before using Copilot.
- Copilot, Test Lab, Agent Chat, and Business Run are not enforced as separate execution modes.
- Copilot history semantics are incorrectly tied to active release state.

The Studio workflow design already defines the intended boundary:

```text
Copilot = construction assistant operating on draft
Test Lab = draft validation
Agent Chat = published interaction using active release
Business Run = production/business execution using active release
```

This design makes that boundary enforceable in backend APIs, execution orchestration, frontend request contracts, and run/history semantics.

## Goal

Make Studio Copilot a draft-only capability that works before publishing, operates only on draft state, and never depends on `active_release_id`.

## Non-Goals

- This design does not change the AgentVersion or AgentRelease data model.
- This design does not redesign the Copilot engine internals.
- This design does not merge Copilot and Test Lab into one surface.
- This design does not add published-Agent Copilot behavior.

## Decisions

| Area | Decision | Rationale |
| --- | --- | --- |
| Copilot execution target | Copilot runs against draft only | Matches Studio product model and avoids release coupling |
| Release dependency | Copilot never requires `active_release_id` | Unpublished Agents must still be buildable |
| Draft identity | Copilot requests must resolve a concrete draft version | Avoids ambiguous "agent only" execution |
| History ownership | Copilot history belongs to draft/version scope, not release scope | Prevents Build and Usage history from mixing |
| Usage boundary | Agent Chat, API usage, tasks, and business runs still require active release | Keeps published behavior stable and explicit |

## Product Boundary

The product must enforce these rules consistently:

```text
Copilot
  Uses draft
  Can create initial draft if none exists
  Can mutate graph, config, and test assets

Test Lab
  Uses draft
  Validates editable state
  Does not require active release

Agent Chat
  Uses active release
  Cannot run unpublished draft changes

Business Run
  Uses active release
  Cannot read Studio draft state
```

The Build surface must never display "publish first to use Copilot." That guidance belongs only to Usage-stage entry points.

## Architecture

### Current Problem

The current `dispatch_copilot()` path is implemented as a release-based execution creator. It creates a run by reading `agent.active_release_id` and rejects the request when no active release exists.

That behavior is correct for Agent Chat and Business Run, but incorrect for Studio Copilot.

### Target Model

Copilot remains a distinct execution engine, but its run ownership changes:

- Current model: `copilot engine + active release`
- Target model: `copilot engine + draft version`

The key distinction is that this is not a Test Lab runtime run. Copilot is still a Copilot execution with Copilot-specific payload and events. It is simply anchored to `agent_version_id` instead of `release_id`.

### Required Backend Path

Studio Copilot should dispatch through a dedicated draft-aware path, conceptually:

```text
POST /v1/copilot/run
  -> dispatch_copilot_draft(...)
  -> AgentRun(release_id=null, agent_version_id=<draft version>)
  -> Execution(executor_kind="copilot")
  -> copilot engine start(...)
```

The orchestrator must not read `agent.active_release_id` for this path.

## API Contract

### Request

Studio Copilot requests must include enough draft context to make the target unambiguous:

```json
{
  "agent_id": "uuid",
  "version_id": "uuid",
  "workspace_id": "uuid",
  "prompt": "Add an HTTP node after Input",
  "graph_context": {},
  "conversation_history": [],
  "mode": "deepagents",
  "provider_name": "optional",
  "model_name": "optional"
}
```

Required semantics:

- `agent_id` identifies the Agent being edited.
- `version_id` identifies the draft version being edited.
- `workspace_id` is used for permission and ownership checks.
- `conversation_history` represents the current Build Copilot session, not published chat history.

### Validation

The API must enforce:

- `version_id` belongs to `agent_id`
- `agent_id` belongs to `workspace_id`
- current user has workspace member access

Recommended error codes:

- `INVALID_DRAFT_VERSION`
- `DRAFT_REQUIRED`
- `FORBIDDEN`

`NO_ACTIVE_RELEASE` must not be returned by the Build Copilot route.

### Route Shape

Two route options are acceptable:

1. Keep `POST /v1/copilot/run`, but redefine it as Studio draft Copilot only.
2. Add `POST /v1/copilot/draft/run` and migrate the frontend to it.

Recommendation: keep the existing path if it is only used by Studio today. That minimizes frontend churn while still fixing the semantics.

## Execution Model

### Run Ownership

Copilot draft runs should be stored as:

- `trigger_source = "copilot"`
- `release_id = null`
- `agent_version_id = <draft version>`

This creates a durable distinction between:

- draft Copilot sessions
- draft Test Lab runs
- published usage runs

### Engine Identity

The executor/engine should remain `copilot`, not the draft runtime engine used by Test Lab. Copilot and Test Lab serve different purposes and emit different shapes of events.

The orchestrator therefore needs a draft creation path that still supports engine overrides:

- draft run ownership from `agent_version_id`
- copilot execution engine
- copilot definition payload overrides

This is the core refactor. Reusing the existing release path is the source of the repeated bugs.

### Follow-Up Messages

Once the first Copilot draft run is created, follow-up messages continue to target the active execution through `send_message(execution_id, message)`.

That behavior can stay unchanged as long as the initial execution was created successfully as a draft-owned Copilot run.

## Draft Creation Behavior

The system must support both edit flows:

### Existing Draft

If a draft version already exists, Copilot operates directly on that draft.

### No Draft Yet

If the Agent has no editable draft version yet, the system should create or materialize one before starting Copilot.

Recommended behavior:

- frontend loads current editable version if present
- if missing, backend or draft bootstrap flow creates one
- Copilot starts only after a concrete draft version exists

This design does not force the bootstrap to happen inside the Copilot API itself, but it does require that Studio has a reliable way to obtain a draft before dispatch.

## History Model

The current error text references "persistent copilot history" as a release feature. That coupling should be removed.

History should be split by product meaning:

- Build Copilot history belongs to draft scope
- Agent Chat history belongs to published chat scope
- Business execution history belongs to operational execution scope

### Minimum Viable History

The first implementation can keep history simple:

- frontend sends `conversation_history` for the current Copilot session
- backend persists execution events for the created Copilot run
- no release lookup is used to reconstruct Build history

### Future Recovery

If the product later wants "resume last Build Copilot session," it should query by draft identity:

- `agent_version_id`
- `trigger_source = "copilot"`

It should not query by `active_release_id`.

## Frontend Changes

The Graph Builder Copilot caller must stop sending only `agentId`.

Required frontend request context:

- `agentId`
- `versionId`
- `workspaceId`

Build-stage UI rules:

- Copilot is enabled without an active release
- Usage-stage chat remains disabled without an active release
- Build errors mention draft problems, not publishing

If no draft version is available yet, the frontend should trigger draft bootstrap before showing the Copilot input as ready.

## Migration Strategy

### Phase 1: Fix the execution boundary

- add draft-aware Copilot dispatch in orchestrator/service/API
- remove `active_release_id` dependency from Studio Copilot
- update frontend request contract to include draft identifiers

### Phase 2: Fix product semantics around history and bootstrap

- separate Build Copilot history from release-based history assumptions
- add draft bootstrap handling when no editable draft exists
- align UI copy with draft-only Copilot behavior

### Phase 3: Harden with tests

- add backend unit tests for draft Copilot dispatch
- add API tests for unpublished Agents
- add frontend tests for Build vs Usage boundary behavior

## Testing Requirements

### Backend

- unpublished Agent can create a Copilot run successfully
- Copilot run stores `agent_version_id` and leaves `release_id` null
- invalid `version_id` returns a draft-specific validation error
- workspace mismatch is rejected
- Usage and Agent Chat paths still reject missing active release

### Frontend

- Build Copilot request includes `versionId` and `workspaceId`
- Build Copilot remains enabled when there is no active release
- Usage chat remains blocked when there is no active release
- Build error copy does not mention publishing for draft validation failures

### Integration

- new Agent with no active release can start Copilot after draft bootstrap
- published Agent still uses active release for Usage-stage chat
- Copilot and Test Lab both work on the same draft version without sharing usage-history logic

## Risks and Guardrails

### Risk: Copilot and Test Lab become conflated

Guardrail:

- keep distinct `trigger_source`
- keep Copilot engine separate from draft runtime execution
- keep UI labels separate

### Risk: partial fallback logic reintroduces release coupling

Guardrail:

- do not keep a silent `if active_release then release path else draft path` implementation inside the same semantic contract unless tests cover both branches explicitly
- prefer a clearly named draft Copilot orchestration method

### Risk: frontend still gates Build on release state

Guardrail:

- add explicit tests for unpublished Build behavior
- review all Build-stage entry points for `active_release_id` checks

## Success Criteria

The design is successful when all of the following are true:

- a never-published Visual Agent can use Copilot in Studio
- Copilot edits only draft state
- Test Lab continues to validate draft state
- Usage-stage chat still requires an active release
- no Build-stage Copilot code path tells the user to publish first
