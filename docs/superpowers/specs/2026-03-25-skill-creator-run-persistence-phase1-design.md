# Skill Creator Run Persistence Phase 1 Design

## Scope

This document is the implementation-focused Phase 1 plan for the long-task persistence architecture.

Phase 1 only migrates **Skill Creator** to the new `run_id + snapshot + replay` model.

Out of scope for this phase:

- full Chat migration
- Copilot migration
- workspace execution migration
- external worker process migration
- generic event-sourcing for every product surface

The goal is to solve the user-facing problem first with the smallest architecture slice that is still production-correct.

## Why Skill Creator First

Skill Creator is the best first target because:

1. It currently has the weakest recovery behavior.
2. Its state shape is bounded and UI-specific.
3. The product value is obvious: users often wait for a generated skill and want to leave the page without losing progress.
4. It already reuses `WS /ws/chat`, so we can preserve the existing execution path while separating transport from UI recovery.

## Target Outcome

After Phase 1:

- starting a Skill Creator generation creates a durable `run_id`
- leaving `/skills/creator` does not lose progress
- returning to `/skills/creator?run=<run_id>` restores:
  - chat messages
  - current streaming assistant buffer
  - running/completed tool calls
  - `preview_skill` result
  - `file_event` projected file tree
  - terminal status
- WebSocket disconnect no longer cancels the underlying Skill Creator task
- the current runtime may still be in-process, but transport is no longer the owner of task state

## Non-Goals

- no attempt to make ordinary Chat fully durable yet
- no attempt to unify Copilot session/history in this phase
- no attempt to move execution to Celery/RQ/Arq/Temporal yet
- no attempt to persist every token delta forever without compaction

## User Flow

### New generation

1. User opens `/skills/creator`.
2. Frontend resolves the Skill Creator graph as today.
3. User sends a prompt.
4. Frontend calls a new create-run API.
5. Backend creates a run and starts the task.
6. Frontend subscribes to the run via `WS /ws/runs`.
7. UI renders snapshot + live events.

### Leave and return

1. User leaves the page during execution.
2. The run keeps executing.
3. User returns via:
   - the same page URL with `?run=<run_id>`, or
   - active-run lookup by graph/thread scope
4. Frontend loads snapshot and subscribes from `last_seq`.
5. User sees previous progress and continues receiving live events.

### Completed run

1. Run finishes.
2. Preview remains restorable from snapshot.
3. User can still save to the skill library later, without relying on the original mounted page.

## Architecture Choices for Phase 1

### Choice 1: Reuse current `WS /ws/chat` execution path

Phase 1 does **not** replace the current graph execution engine.

It reuses:

- `ChatWsHandler`
- existing graph construction
- existing stream event conversion
- existing `preview_skill` tool flow

But it adds a run persistence layer beside it.

Reason:

- minimal blast radius
- faster delivery
- lower risk than rewriting task orchestration immediately

### Choice 2: Add a dedicated run subscription channel

Phase 1 adds a new subscription-only WebSocket:

- `WS /ws/runs`

Reason:

- keep `WS /ws/chat` as command/execution compatibility layer
- avoid overloading the current request-oriented WS client with replay semantics
- enable later migration of Chat and Copilot onto the same run-subscription transport

### Choice 3: DB is durable truth, Redis is optional hot path

Phase 1 stores durable run state in Postgres:

- run metadata
- event rows
- snapshot rows

Redis is optional acceleration for:

- live fan-out
- short-lived latest snapshot cache
- "active run by scope" cache

If Redis is unavailable, the feature still works through DB polling + replay.

## Data Model

Phase 1 adds three tables, exactly as defined in the broader design, but only uses the subset required by Skill Creator.

### `agent_runs`

Fields used in Phase 1:

- `id`
- `user_id`
- `workspace_id`
- `graph_id`
- `thread_id`
- `run_type` = `skill_creator`
- `source` = `skills_creator_page`
- `status`
- `title`
- `request_payload`
- `result_summary`
- `error_code`
- `error_message`
- `trace_id`
- `started_at`
- `finished_at`
- `last_seq`
- `created_at`
- `updated_at`

### `agent_run_events`

Fields used in Phase 1:

- `id`
- `run_id`
- `seq`
- `event_type`
- `payload`
- `trace_id`
- `observation_id`
- `parent_observation_id`
- `created_at`

### `agent_run_snapshots`

Fields used in Phase 1:

- `run_id`
- `last_seq`
- `status`
- `projection`
- `updated_at`

## Projection Shape for Skill Creator

Phase 1 uses a Skill-Creator-specific projection reducer.

```json
{
  "version": 1,
  "run_type": "skill_creator",
  "status": "running",
  "graph_id": "uuid",
  "thread_id": "thread-id",
  "edit_skill_id": "optional-skill-id",
  "messages": [
    {
      "id": "msg-user-1",
      "role": "user",
      "content": "Build a skill for ...",
      "timestamp": 1740000000000
    },
    {
      "id": "msg-ai-1",
      "role": "assistant",
      "content": "Working on it...",
      "timestamp": 1740000001000,
      "isStreaming": true,
      "tool_calls": []
    }
  ],
  "current_assistant_message_id": "msg-ai-1",
  "preview_data": null,
  "file_tree": {},
  "interrupt": null,
  "meta": {
    "current_request_id": "legacy-request-id",
    "last_node": "preview_skill"
  }
}
```

Notes:

- `messages` is the UI-ready structure used by `frontend/app/skills/creator/page.tsx`
- `file_tree` is the already-projected map currently built in local state
- `preview_data` stores the parsed `preview_skill` payload
- terminal status lives both in `agent_runs.status` and `snapshot.status`

## Canonical Run Events for Phase 1

Phase 1 only needs a small canonical event vocabulary.

### Required event types

- `user_message_added`
- `assistant_message_started`
- `content_delta`
- `tool_start`
- `tool_end`
- `file_event`
- `interrupt`
- `error`
- `done`
- `status`

### Canonical payload examples

```json
{
  "event_type": "user_message_added",
  "payload": {
    "message": {
      "id": "msg-user-1",
      "role": "user",
      "content": "Create a skill for ...",
      "timestamp": 1740000000000
    }
  }
}
```

```json
{
  "event_type": "assistant_message_started",
  "payload": {
    "message": {
      "id": "msg-ai-1",
      "role": "assistant",
      "content": "",
      "timestamp": 1740000001000,
      "isStreaming": true,
      "tool_calls": []
    }
  }
}
```

```json
{
  "event_type": "content_delta",
  "payload": {
    "message_id": "msg-ai-1",
    "delta": "I will scaffold the skill ..."
  }
}
```

```json
{
  "event_type": "tool_end",
  "payload": {
    "message_id": "msg-ai-1",
    "tool_name": "preview_skill",
    "tool_output": {
      "skill_name": "my-skill",
      "files": [],
      "validation": { "valid": true, "errors": [], "warnings": [] }
    }
  }
}
```

### Mapping from existing chat stream events

Phase 1 will not invent a second internal event stream from the graph engine.

Instead, when the current runtime emits chat WS events:

- `content` -> `content_delta`
- `tool_start` -> `tool_start`
- `tool_end` -> `tool_end`
- `file_event` -> `file_event`
- `interrupt` -> `interrupt`
- `error` -> `error`
- `done` -> `done`
- `status` -> `status`

Additional synthetic events will be written for:

- `user_message_added`
- `assistant_message_started`

These do not currently exist as transport events but are needed to reconstruct page state deterministically.

## API Design

Phase 1 adds a dedicated runs API.

### `POST /api/v1/runs/skill-creator`

Create a Skill Creator run and start execution.

Request:

```json
{
  "message": "Build a skill that ...",
  "graph_id": "uuid",
  "thread_id": null,
  "edit_skill_id": "optional-skill-id"
}
```

Response:

```json
{
  "success": true,
  "data": {
    "run_id": "uuid",
    "thread_id": "thread-id",
    "status": "running"
  }
}
```

Backend behavior:

1. Create `agent_runs` row.
2. Create initial snapshot with empty assistant state.
3. Start runtime task.
4. Return `run_id`.

### `GET /api/v1/runs/{run_id}`

Returns run metadata.

Used by the page to determine whether the run is still active and who owns it.

### `GET /api/v1/runs/{run_id}/snapshot`

Returns:

```json
{
  "success": true,
  "data": {
    "run_id": "uuid",
    "status": "running",
    "last_seq": 42,
    "projection": { "...": "..." }
  }
}
```

### `GET /api/v1/runs/{run_id}/events?after_seq=42&limit=500`

Returns ordered replay events after the given sequence.

This is needed both for:

- WS replay fallback
- debugging
- future polling fallback if WS is unavailable

### `GET /api/v1/runs/active/skill-creator?graph_id=<uuid>&thread_id=<id>`

Returns the latest active Skill Creator run for the current user and scope.

Used when:

- page URL does not yet include `run`
- browser is refreshed mid-task

Response:

- `null` if no active run exists
- latest running or interrupt-wait run if found

### `POST /api/v1/runs/{run_id}/cancel`

Explicitly cancel the run.

This replaces "disconnect means cancel" semantics for Skill Creator.

## WebSocket Design

### New endpoint

- `WS /ws/runs`

### Client frames

```json
{ "type": "subscribe", "run_id": "uuid", "after_seq": 0 }
{ "type": "unsubscribe", "run_id": "uuid" }
{ "type": "ping" }
```

### Server frames

```json
{
  "type": "snapshot",
  "run_id": "uuid",
  "last_seq": 42,
  "data": { "...projection..." }
}
```

```json
{
  "type": "event",
  "run_id": "uuid",
  "seq": 43,
  "event_type": "content_delta",
  "data": { "message_id": "msg-ai-1", "delta": "..." }
}
```

```json
{ "type": "replay_done", "run_id": "uuid", "last_seq": 43 }
{ "type": "run_status", "run_id": "uuid", "status": "running" }
{ "type": "pong" }
{ "type": "ws_error", "message": "..." }
```

### Replay semantics

When the client subscribes:

1. load snapshot
2. send `snapshot`
3. load and emit all events with `seq > after_seq`
4. send `replay_done`
5. attach subscriber to live event bus

## Backend File Plan

### New files

#### Models

- `backend/app/models/agent_run.py`

Contains:

- `AgentRun`
- `AgentRunEvent`
- `AgentRunSnapshot`
- run status enum

#### Repository

- `backend/app/repositories/agent_run.py`

Methods:

- `create_run(...)`
- `get_run(...)`
- `get_snapshot(...)`
- `append_event(...)`
- `list_events_after(...)`
- `update_snapshot(...)`
- `find_latest_active_skill_creator_run(...)`
- `mark_status(...)`

#### Schemas

- `backend/app/schemas/runs.py`

Contains request/response models for:

- create run
- run detail
- snapshot detail
- event list

#### Service

- `backend/app/services/run_service.py`

Responsibilities:

- create run
- append event with monotonically increasing `seq`
- apply Skill Creator reducer
- update snapshot
- publish live event to Redis / subscriber manager
- resolve active run by scope

#### Reducer

- `backend/app/services/run_reducers/skill_creator.py`

Pure reducer:

- `(projection, canonical_event) -> new_projection`

#### WebSocket subscription handler

- `backend/app/websocket/run_subscription_handler.py`

Responsibilities:

- authenticate subscriber
- subscribe/unsubscribe by `run_id`
- send snapshot
- send replay
- attach to live fan-out

#### API router

- `backend/app/api/v1/runs.py`

### Files to modify

#### `backend/app/models/__init__.py`

Export new models.

#### `backend/app/api/v1/__init__.py`

Register `runs_router`.

#### `backend/app/main.py`

Add:

- `@app.websocket("/ws/runs")`

#### `backend/app/core/redis.py`

Add generic run methods:

- `publish_run_event(run_id, event)`
- optional `set_run_snapshot_cache(run_id, snapshot)`
- optional `get_run_snapshot_cache(run_id)`

Do not create Skill-Creator-specific Redis methods.

#### `backend/app/websocket/chat_ws_handler.py`

Modify only the Skill Creator path in Phase 1:

- do not own page recovery state
- when metadata indicates Skill Creator mode, write canonical run events through `RunService`
- on disconnect, do not cancel the underlying run if the task belongs to a persisted Skill Creator run

Implementation note:

The least disruptive approach is:

- inject `run_id` into the execution path
- wrap `_send_event_from_sse(...)` so that every outgoing event is also normalized and persisted

#### `backend/app/api/v1/chat.py`

No major API resurrection.

Possible small changes:

- expose helper(s) for event normalization if needed
- leave message persistence logic intact for now

### Migration

Add Alembic migration:

- `backend/alembic/versions/<timestamp>_add_agent_run_tables.py`

## Backend Execution Strategy

Phase 1 keeps execution in-process, but changes ownership semantics.

### Required behavior change

Current behavior:

- `ChatWsHandler.run()` ends
- `_cancel_all_tasks()` stops tasks on disconnect

Phase 1 behavior for persisted Skill Creator runs:

- disconnect detaches only the subscriber
- the in-process task continues
- task completion writes final snapshot and terminal event even if no subscriber is connected

### Minimal implementation approach

Add a process-local runtime registry:

- `backend/app/services/run_runtime_registry.py`

Stores:

- `run_id -> asyncio.Task`
- optional metadata such as `thread_id`, `user_id`, `run_type`

`ChatWsHandler` no longer treats the socket as the owner of those tasks for persisted Skill Creator runs.

This is not the final multi-worker design, but it is sufficient for Phase 1.

## Frontend File Plan

### New files

#### API service

- `frontend/services/runService.ts`

Methods:

- `createSkillCreatorRun(...)`
- `getRun(runId)`
- `getRunSnapshot(runId)`
- `getRunEvents(runId, afterSeq)`
- `findActiveSkillCreatorRun(graphId, threadId?)`
- `cancelRun(runId)`

#### WS client

- `frontend/lib/ws/runs/runWsClient.ts`
- `frontend/lib/ws/runs/types.ts`

Capabilities:

- connect/reconnect
- subscribe by `run_id`
- replay sequencing
- connection-state listeners

#### Hook

- `frontend/app/skills/creator/hooks/useSkillCreatorRun.ts`

Responsibilities:

- create run
- restore snapshot
- subscribe to replay/live events
- reduce canonical run events into local React state
- expose `sendMessage`, `stopRun`, `resumeExistingRun`

### Files to modify

#### `frontend/lib/api-client.ts`

Add:

- `runs: 'runs'`

#### `frontend/app/skills/creator/page.tsx`

Major refactor:

- stop owning the source of truth in raw `useState`
- page becomes a thin composition over `useSkillCreatorRun`
- read `run` from search params
- if `run` exists, restore that run
- otherwise, optionally resolve latest active run by scope

Important:

The page may still keep transient UI state like dialog visibility locally.
It should not keep durable run state only in component memory.

## Frontend State Model

Phase 1 can preserve the current `Message` and `SkillPreviewData` UI shapes.

The hook should expose:

```ts
interface SkillCreatorRunState {
  runId: string | null
  threadId: string | null
  status: 'idle' | 'running' | 'interrupt_wait' | 'completed' | 'failed' | 'cancelled'
  messages: Message[]
  isProcessing: boolean
  previewData: SkillPreviewData | null
  fileTree: Record<string, { action: string; size?: number; timestamp?: number }>
  isConnected: boolean
  lastSeq: number
}
```

`isProcessing` should derive from `status`, not be an independent truth source.

## URL Strategy

Phase 1 adds `run` query param:

- `/skills/creator?run=<run_id>`
- `/skills/creator?edit=<skill_id>&run=<run_id>`

When a new run is created:

- update the URL with `run=<run_id>` using `router.replace`

This gives the browser a stable recovery pointer across refresh/navigation.

## Reducer Rules

### `user_message_added`

- append user message

### `assistant_message_started`

- append assistant placeholder
- set `current_assistant_message_id`
- set `status=running`

### `content_delta`

- append delta to `current_assistant_message_id`

### `tool_start`

- append running tool call to current assistant message

### `tool_end`

- close most recent matching running tool
- if tool is `preview_skill`, parse and set `preview_data`

### `file_event`

- update `file_tree`

### `interrupt`

- set `interrupt`
- mark assistant message not streaming
- set `status=interrupt_wait`

### `error`

- append error decoration if needed
- set status `failed`
- mark assistant message not streaming

### `done`

- mark assistant message not streaming
- set status `completed`

Reducers must be deterministic and idempotent under duplicate event delivery by `seq`.

## Persistence Frequency

### Event rows

Persist every canonical event.

### Snapshot writes

Phase 1 policy:

- flush snapshot immediately for structural events:
  - `user_message_added`
  - `assistant_message_started`
  - `tool_start`
  - `tool_end`
  - `file_event`
  - `interrupt`
  - `error`
  - `done`
- for `content_delta`, buffer and flush snapshot at most every 500ms per run
- always flush pending content before writing terminal events

Reason:

- enough durability for user-visible progress
- avoids excessive DB writes per token

## Redis Usage in Phase 1

Redis is optional but recommended.

### Use cases

- publish live run events to WS subscribers
- cache latest snapshot for fast reconnect
- cache "latest active run by scope" lookup

### Fallback

If Redis is unavailable:

- API still works
- snapshot still restores state
- WS replay still works from DB
- live delivery can degrade to polling if necessary

Phase 1 should not hard-require Redis.

## Observability

Whenever available, canonical run events should preserve:

- `trace_id`
- `observation_id`
- `parent_observation_id`

This is already present in the stream envelopes produced by `StreamEventHandler`.

We should persist these fields into `agent_run_events` so later UI or admin tools can deep-link into:

- `/api/v1/traces/{trace_id}`

## Access Control

All run operations require authenticated user access.

Rules:

- only owner can access personal Skill Creator runs
- if a future workspace-shared Skill Creator exists, workspace access rules can be layered later

Phase 1 can keep ownership model simple:

- `AgentRun.user_id` must equal current user id

## Detailed Implementation Sequence

### Step 1

Add DB models and migration.

### Step 2

Add repository + `RunService` + Skill Creator reducer.

### Step 3

Add runs API endpoints.

### Step 4

Add `WS /ws/runs` subscription handler with:

- snapshot
- replay
- live fan-out

### Step 5

Refactor Skill Creator frontend to:

- create run
- store `run_id` in URL
- restore snapshot
- subscribe to run

### Step 6

Modify `ChatWsHandler` Skill Creator path so disconnect does not cancel the underlying run task.

### Step 7

Add tests and verify:

- leave page -> return -> progress still visible
- refresh page mid-run -> progress restored
- finish run without active subscriber -> final preview restorable

## Rollback Strategy

Phase 1 is safe to rollback if we:

- keep current Skill Creator execution path intact
- add the run layer in parallel

Rollback path:

- stop creating persisted runs
- revert frontend to old direct `sendChat` flow
- leave run tables unused

No existing user-facing APIs need to be removed in this phase.

## Testing Plan

### Backend unit

- reducer correctness for every event type
- sequence allocation correctness
- active run lookup correctness

### Backend integration

- create run -> emit events -> snapshot updates correctly
- subscribe with `after_seq=0` -> receive snapshot and replay
- disconnect subscriber -> task continues
- reconnect -> receive missing events

### Frontend unit

- snapshot restores `messages/preview/fileTree`
- event replay updates state without duplication
- query param `run` drives restoration

### E2E

1. Start Skill Creator generation.
2. Wait until there is partial content and at least one tool call.
3. Navigate away.
4. Navigate back to `/skills/creator?run=<run_id>`.
5. Confirm previous content and tool state are visible.
6. Wait for `preview_skill`.
7. Confirm preview is rendered.

## Risks

### Risk 1: In-process runtime still dies on server restart

True. Phase 1 solves page-switch/reconnect recovery, not process crash recovery.

Mitigation:

- document this limitation
- keep architecture aligned so Phase 2/3 can move execution to workers

### Risk 2: Duplicate writes from old and new state paths

Mitigation:

- runs snapshot is the Skill Creator recovery source
- current page-local state becomes render cache only
- avoid parallel "manual reconstruction" paths once hook migration is complete

### Risk 3: WS replay and live event race

Mitigation:

- subscription handler must:
  - load snapshot
  - replay through a fixed `last_seq`
  - only then attach live subscriber

## Exact File Checklist

### Backend new

- `backend/app/models/agent_run.py`
- `backend/app/repositories/agent_run.py`
- `backend/app/schemas/runs.py`
- `backend/app/services/run_service.py`
- `backend/app/services/run_runtime_registry.py`
- `backend/app/services/run_reducers/skill_creator.py`
- `backend/app/api/v1/runs.py`
- `backend/app/websocket/run_subscription_handler.py`
- `backend/alembic/versions/<new>_add_agent_run_tables.py`

### Backend modify

- `backend/app/models/__init__.py`
- `backend/app/api/v1/__init__.py`
- `backend/app/main.py`
- `backend/app/core/redis.py`
- `backend/app/websocket/chat_ws_handler.py`

### Frontend new

- `frontend/services/runService.ts`
- `frontend/lib/ws/runs/types.ts`
- `frontend/lib/ws/runs/runWsClient.ts`
- `frontend/app/skills/creator/hooks/useSkillCreatorRun.ts`

### Frontend modify

- `frontend/lib/api-client.ts`
- `frontend/app/skills/creator/page.tsx`

## Success Criteria

Phase 1 is successful if:

- Skill Creator can be left and re-entered without losing prior visible progress
- preview and file-tree state restore correctly
- disconnecting the page no longer cancels the task
- no existing Chat/Copilot behavior is broken
- the new run primitives are reusable for later Chat/Copilot migration

