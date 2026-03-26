# Long-Task Progress Persistence Design

## Goal

Provide a production-grade architecture for long-running agent tasks so that:

- a task keeps running when the user switches pages or refreshes the browser
- the user can return later and still see prior progress
- progress can be replayed and resumed reliably across reconnects
- Chat, Skill Creator, Copilot, and workspace execution use the same underlying runtime model

This design targets the current JoySafeter implementation and explicitly replaces the "page-local state + live WebSocket only" model where needed.

## Status

Proposed on 2026-03-25.

## Problem

The current codebase has three partially different real-time patterns:

1. `WS /ws/chat` streams Chat and Skill Creator events directly from an in-process task.
2. Copilot uses a session-oriented Redis Pub/Sub model with partial result recovery.
3. Execution/trace APIs persist observations, but mainly as observability data rather than UI recovery state.

This causes a production gap for long tasks:

- if the UI component unmounts, local progress state is lost
- if the WebSocket disconnects, the backend currently cancels Chat tasks
- restoring the page can recover final history in some cases, but not in-progress state
- Skill Creator preview/file-tree state is not durably recoverable
- there is no single "run" abstraction shared by all long-running agent flows

## Current State Analysis

### Chat / Skill Creator

`backend/app/websocket/chat_ws_handler.py` currently owns both transport and task lifetime:

- the handler creates `asyncio.Task`s per request
- on `WebSocketDisconnect`, `_cancel_all_tasks()` stops and cancels all running tasks
- messages and trace data are persisted in `finally`, mostly after the turn completes

This means transport loss is treated as task termination.

Skill Creator in `frontend/app/skills/creator/page.tsx` keeps all progress in page-local React state:

- `messages`
- `isProcessing`
- `threadId`
- `previewData`
- `fileTree`

When the page is left and remounted, there is no durable source for the in-progress view.

### Copilot

Copilot is closer to the target model:

- it has a durable history model
- it caches results in Redis
- it can reconnect and receive cached `result` + `done`

But it still does not provide full event replay or a general long-task runtime usable by Chat and Skill Creator.

### Trace / Execution

The trace system already provides:

- `trace_id`
- `observation_id`
- hierarchical observation structure
- query APIs under `/v1/traces`

This is valuable for observability and debugging, but it should not become the primary UI recovery store for product state such as:

- streamed assistant message buffers
- Skill preview payloads
- file tree deltas
- interrupt UI state
- conversation-scoped "what the user last saw"

## Design Principles

1. Transport is not task ownership.
2. A page is a subscriber, not the source of truth.
3. Every long-running task has a stable `run_id`.
4. Progress is recoverable through snapshot + replay.
5. Redis may accelerate delivery, but the database is the durable source of truth.
6. Trace/observation remains an observability layer, not the primary UI projection.

## Target Architecture

Introduce a new shared runtime layer: `Agent Run Center`.

### Core concepts

#### 1. Agent Run

A long-running task entity with stable identity and lifecycle.

Examples:

- one Chat turn
- one Skill Creator generation/regeneration turn
- one Copilot generation session
- one workspace graph execution

Each run has:

- `run_id`
- owner and scope (`user_id`, optional `workspace_id`, optional `graph_id`, optional `thread_id`)
- `run_type`
- `status`
- `started_at`, `finished_at`
- current projection snapshot
- terminal result or error metadata

#### 2. Run Event Log

An append-only ordered event stream for each run.

Every user-visible progress update is written as a run event:

- `content_delta`
- `tool_start`
- `tool_end`
- `node_start`
- `node_end`
- `file_event`
- `interrupt`
- `preview_skill`
- `status`
- `error`
- `done`

Each event has a monotonically increasing `seq`.

#### 3. Run Snapshot / Projection

A denormalized current-state document derived from events.

It exists to make page restoration fast and deterministic.

The snapshot contains only UI-relevant aggregate state, for example:

- current assistant message buffers
- completed messages shown so far
- tool-call states
- active node list
- interrupt payload
- Skill Creator preview payload
- file tree projection
- latest terminal state
- last emitted `seq`

The UI restores from snapshot first, then replays any missing events after `last_seq`.

## High-Level Flow

### Start

1. Frontend creates or resumes a page-level view.
2. Frontend starts a task through an API or WS command.
3. Backend creates `agent_runs` row and returns `run_id`.
4. Runtime begins execution independently of the WebSocket connection.
5. Runtime appends events to `agent_run_events`.
6. Runtime updates `agent_run_snapshots`.
7. Live subscribers receive events over WS.

### Reconnect / Return to page

1. Frontend loads run summary and snapshot by `run_id`.
2. Frontend opens WS subscription with `after_seq=<snapshot.last_seq>`.
3. Backend replays missing events from durable store.
4. Backend then switches the subscriber to live event delivery.

### Completion

1. Runtime writes terminal event (`done` or `error` or `interrupted`).
2. Snapshot status is finalized.
3. Optional downstream persistence runs complete.
4. Subscribers receive terminal frame.
5. Future page loads restore from snapshot/history without requiring the original transport session.

## Data Model

Add three new tables.

### `agent_runs`

Primary run record.

Suggested columns:

- `id UUID PK`
- `user_id VARCHAR NOT NULL`
- `workspace_id UUID NULL`
- `graph_id UUID NULL`
- `thread_id VARCHAR NULL`
- `run_type VARCHAR NOT NULL`
- `source VARCHAR NOT NULL`
- `status ENUM('queued','running','interrupt_wait','completed','failed','cancelled')`
- `title VARCHAR NULL`
- `request_payload JSONB NULL`
- `result_summary JSONB NULL`
- `error_code VARCHAR NULL`
- `error_message TEXT NULL`
- `trace_id UUID NULL`
- `started_at TIMESTAMPTZ NOT NULL`
- `finished_at TIMESTAMPTZ NULL`
- `last_seq BIGINT NOT NULL DEFAULT 0`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Indexes:

- `(user_id, created_at DESC)`
- `(thread_id, created_at DESC)`
- `(graph_id, created_at DESC)`
- `(status, updated_at DESC)`

### `agent_run_events`

Append-only event log.

Suggested columns:

- `id UUID PK`
- `run_id UUID NOT NULL FK agent_runs(id)`
- `seq BIGINT NOT NULL`
- `event_type VARCHAR NOT NULL`
- `payload JSONB NOT NULL`
- `trace_id UUID NULL`
- `observation_id UUID NULL`
- `parent_observation_id UUID NULL`
- `created_at TIMESTAMPTZ NOT NULL`

Constraints:

- unique `(run_id, seq)`

Indexes:

- `(run_id, seq)`
- `(run_id, created_at)`

### `agent_run_snapshots`

Latest UI projection.

Suggested columns:

- `run_id UUID PK FK agent_runs(id)`
- `last_seq BIGINT NOT NULL`
- `status VARCHAR NOT NULL`
- `projection JSONB NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

`projection` is intentionally product-oriented, not event-normalized.

## Snapshot Shape

Recommended baseline shape:

```json
{
  "version": 1,
  "run_type": "skill_creator",
  "status": "running",
  "thread_id": "chat-thread-id",
  "graph_id": "graph-id",
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "content": "Build a skill for ...",
      "timestamp": 1740000000000
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "content": "I will create ...",
      "is_streaming": true,
      "tool_calls": []
    }
  ],
  "current_assistant_message_id": "msg-2",
  "active_tools": [],
  "preview_data": null,
  "file_tree": {},
  "interrupt": null,
  "meta": {
    "last_node": "preview_skill"
  }
}
```

Skill Creator can extend this with:

- `preview_data`
- `validation`
- `file_tree`

Copilot can extend this with:

- `thought_steps`
- `actions`

Workspace execution can extend this with:

- `execution_tree`
- `route_decisions`
- `pending_interrupts`

## Transport Design

### New WS concept: run subscription

Keep `WS /ws/chat` for command compatibility in the short term, but introduce a run-subscription protocol underneath.

Recommended new endpoint:

- `WS /ws/runs`

Client frames:

```json
{ "type": "subscribe", "run_id": "<uuid>", "after_seq": 120 }
{ "type": "unsubscribe", "run_id": "<uuid>" }
{ "type": "ping" }
```

Server frames:

```json
{ "type": "snapshot", "run_id": "<uuid>", "last_seq": 120, "data": { ...projection... } }
{ "type": "event", "run_id": "<uuid>", "seq": 121, "event_type": "content_delta", "data": { ... } }
{ "type": "replay_done", "run_id": "<uuid>", "last_seq": 128 }
{ "type": "run_status", "run_id": "<uuid>", "status": "running" }
{ "type": "ws_error", "message": "..." }
{ "type": "pong" }
```

Rules:

1. On subscribe, server loads snapshot and sends it first.
2. If `after_seq < snapshot.last_seq`, server replays events `(after_seq, snapshot.last_seq]`.
3. Then server attaches subscriber to live delivery.
4. Multiple subscribers may attach to the same run.
5. Disconnecting a subscriber does not cancel the run.

## Command / Start API

Long-running tasks should be started through a create-run action that returns `run_id`.

Recommended pattern:

### Chat / Skill Creator

Option A:

- continue using `WS /ws/chat` for `chat` and `resume`
- server immediately creates a run
- first server event includes `run_id`
- frontend stores `run_id` in route state / page state / local storage

Option B:

- add `POST /v1/runs/chat`
- response returns `run_id`
- runtime starts
- frontend subscribes via `WS /ws/runs`

Production recommendation: move to Option B. It separates command submission from event delivery cleanly.

### Copilot

- replace opaque `session_id` semantics with `run_id`
- keep compatibility aliases temporarily if needed

### Workspace execution

- graph execution start API returns `run_id`
- execution panel subscribes to that run

## Runtime Ownership

### Required change

Do not let WebSocket handlers own task lifetime.

Current `ChatWsHandler` behavior on disconnect should be changed:

- disconnect should unregister the subscriber
- it must not stop the underlying run unless the client explicitly sends cancel

### Recommended execution model

Short term:

- keep in-process execution if necessary
- move run ownership into a `RunRuntimeRegistry`
- let WS handler call runtime service, not hold raw task maps as the source of truth

Long term:

- move long-running task execution into worker processes
- use Redis streams / queue / task runner for dispatch
- web nodes become stateless control + subscription servers

Production recommendation:

- web app may still publish live events
- worker owns task execution
- DB remains durable truth
- Redis is the hot fan-out path

## Event Write Path

For each emitted internal event:

1. normalize into canonical run event
2. append to `agent_run_events`
3. apply reducer to snapshot projection
4. update `agent_run_snapshots`
5. publish live event to Redis channel
6. WS subscribers forward event to frontend

This ordering ensures replay correctness.

Optimization:

- events may be batched in small transactions
- snapshot writes may be throttled for high-frequency deltas
- but terminal events must flush synchronously

## Relationship With Trace System

Do not replace traces.

Instead:

- keep `ExecutionTrace` and `ExecutionObservation` as observability records
- link run events to traces using `trace_id`, `observation_id`, `parent_observation_id`
- allow UI drill-down from run view into technical trace detail

This preserves the value of the existing stream event handler while avoiding misuse of traces as the only product-state store.

## Frontend Design

Introduce a shared run-view model.

### Shared hooks/services

- `runService.getRun(runId)`
- `runService.getSnapshot(runId)`
- `runService.listRunEvents(runId, afterSeq)`
- `useRunSubscription(runId, reducer)`
- `useRunRecovery(runId, projectionAdapter)`

### Page behavior

When entering a page:

1. load the latest active run for the page scope if one exists
2. restore snapshot immediately
3. subscribe from `snapshot.last_seq`
4. show connection state separately from run state

Important:

- `isConnected` is transport state
- `run.status === running` is business state

These must not be conflated.

### Skill Creator

Skill Creator should no longer keep progress only in local `useState`.

It should:

- create or attach to a `run_id`
- restore `messages`, `previewData`, and `fileTree` from snapshot
- continue rendering live events from replay/live subscription

### Chat

Chat should separate:

- durable conversation history
- active run state for the current unfinished turn

Completed messages may still load from conversation history, while unfinished turn state comes from active run snapshot.

### Copilot

Copilot should migrate from custom session recovery to the shared run layer:

- `session_id` becomes compatibility wrapper around `run_id`
- final action/result cache moves into snapshot/result summary

### Workspace execution

Execution panel should consume run snapshot + event replay rather than relying only on currently mounted store state.

## Reducer Model

Each product surface gets a projection reducer.

Examples:

- `chatRunReducer`
- `skillCreatorRunReducer`
- `copilotRunReducer`
- `workspaceExecutionRunReducer`

Each reducer:

- consumes canonical run events
- updates product snapshot
- is deterministic and replay-safe

This gives the system event-sourcing semantics without forcing the UI to render directly from raw event rows.

## Compatibility / Migration Plan

### Phase 1: Skill Creator first

Why:

- it has the weakest recovery model today
- it is the clearest user-facing pain point
- its projection shape is straightforward

Deliverables:

- new run tables
- run snapshot/event services
- Skill Creator creates run and stores preview/file-tree projection
- page re-entry restores from run
- disconnect no longer cancels Skill Creator task

### Phase 2: Chat

Deliverables:

- Chat turns create `run_id`
- active unfinished turn restored from run snapshot
- `ChatWsHandler` disconnect no longer aborts task
- stop/resume become explicit run commands

### Phase 3: Copilot

Deliverables:

- unify session persistence under run model
- keep existing history endpoint as compatibility view over run-derived data or existing chat table

### Phase 4: Workspace execution

Deliverables:

- execution panel reads run snapshot and event replay
- traces become linked technical detail, not the only way to inspect old progress

## Failure Handling

### WebSocket disconnect

- subscriber detached
- run continues
- reconnect replays from `after_seq`

### Browser refresh

- page reloads
- active run is rediscovered from route scope or active-run query
- snapshot restored

### Web node restart

- live WS subscribers disconnect
- workers continue if runtime is externalized
- reconnect recovers from DB + Redis

### Worker crash

- run status transitions to `failed` or `queued_for_recovery`
- terminal event written if possible
- UI shows durable failure state

### Duplicate event delivery

- reducers must be idempotent by `(run_id, seq)`
- frontend should ignore already-applied `seq`

## Security / Access Control

- all run queries must validate `user_id` ownership or workspace access
- `run_id` must not be guessable enough to bypass auth; UUID is fine but auth is still mandatory
- subscription endpoint must validate access per run
- snapshots may contain file paths and tool outputs, so apply the same permission model as the originating graph/workspace

## Testing Strategy

### Backend unit

- reducer updates snapshot correctly from canonical events
- event append increments `seq` correctly under concurrency
- replay returns ordered events
- disconnect does not cancel run
- explicit cancel does cancel run

### Backend integration

- create Skill Creator run, disconnect WS, reconnect, observe replayed progress
- create Chat run, switch pages, reload, restore unfinished turn
- verify terminal state flushes snapshot and events

### Frontend unit

- restoring from snapshot produces correct page state
- replay after snapshot does not duplicate messages or tools
- `isConnected` transitions do not erase business progress

### E2E

1. Start Skill Creator generation.
2. Leave the page mid-run.
3. Return after 10 seconds.
4. Previously emitted progress is visible.
5. New progress continues live.
6. Final preview is still available.

## Open Questions

1. Should active runs be discoverable by scope (`thread_id`, `graph_id`) or only by direct `run_id`?
Recommendation: support both. UI prefers scope lookup on fresh load and `run_id` on exact resume.

2. Should message history be derived from run snapshots or remain in existing conversation tables?
Recommendation: keep conversation tables for durable completed chat history; use run snapshot only for unfinished turns.

3. Should snapshots be updated on every token delta?
Recommendation: no. Batch high-frequency deltas in memory/Redis and flush snapshot periodically, but always flush on terminal events and major structural events.

## Recommended First Implementation

The first production-meaningful cut should be:

- add `agent_runs`, `agent_run_events`, `agent_run_snapshots`
- build a minimal `RunService`
- migrate Skill Creator to create a run and persist:
  - messages
  - current streaming assistant content
  - `preview_skill` output
  - `file_event` projection
- add `GET /v1/runs/{run_id}`
- add `GET /v1/runs/{run_id}/snapshot`
- add `GET /v1/runs/active?graph_id=...&thread_id=...`
- add `WS /ws/runs` subscribe/replay
- modify Chat/Skill execution runtime so WS disconnect detaches subscriber instead of cancelling the task

This is the smallest slice that materially solves the user-facing problem while creating the correct long-term foundation.
