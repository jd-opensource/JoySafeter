# Chat Run Center Integration Design

**Date:** 2026-04-06
**Status:** Approved
**Phase:** Phase 2 of the Long-Task Progress Persistence roadmap (see `2026-03-25-long-task-progress-persistence-design.md`)

## Problem

Chat sessions in `/chat` are not tracked in Run Center. When the WebSocket disconnects, the agent task is cancelled. Users have no way to:

- Monitor active Chat runs alongside Skill Creator runs
- Recover from accidental disconnects
- Review historical Chat turn execution details (events, tool calls, node logs)

## Goals

1. All Chat conversations appear in Run Center as trackable runs
2. WS disconnect does not cancel the agent — it continues running
3. Users can reconnect and resume observing progress
4. Chat runs viewable in Run Center detail page (events, messages, tool calls)

## Non-Goals

- Copilot integration (Phase 3)
- Workspace execution integration (Phase 4)
- Changing the Chat UI layout or message display

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Run granularity | 1 turn = 1 run | Clean lifecycle (start → end). Thread-level run would require reworking the status machine for multi-turn pause/resume. Same-thread runs linked via `thread_id`. |
| Integration pattern | Extend `extension` mechanism | Reuse the proven skill_creator path. Frontend explicitly creates run before WS frame. Consistent, predictable, debuggable. |
| Run Center display | Flat list + thread filter | Consistent with skill_creator display. Thread grouping via `thread_id` tag/filter. |
| "Open" navigation | Run Center detail page | Show events, messages, and tool calls within Run Center, not redirect to `/chat`. |
| Disconnect behavior | Persist on disconnect | Same as skill_creator. Heartbeat continues. User reconnects via `/ws/runs` subscription. |

---

## Section 1: Backend Data Model & Agent Registration

### 1.1 Register `chat` Agent

New file: `backend/app/services/run_reducers/chat.py`

```python
AgentRegistry.register(AgentDefinition(
    name="chat",
    display_name="Chat",
    default_run_type="chat_turn",
    reducer=chat_run_reducer,
    initial_projection=chat_initial_projection,
))
```

Register in `backend/app/services/run_reducers/__init__.py` alongside `skill_creator`.

### 1.2 Chat Projection Schema

```json
{
  "version": 1,
  "run_type": "chat_turn",
  "status": "running",
  "thread_id": "uuid-string",
  "graph_id": "uuid-string",
  "user_message": {
    "content": "user's message text",
    "files": []
  },
  "assistant_message": {
    "id": "msg-uuid",
    "content": "",
    "tool_calls": []
  },
  "node_execution_log": [],
  "interrupt": null,
  "meta": {
    "model": "model-name",
    "started_at": "ISO-8601"
  }
}
```

Key differences from skill_creator projection:
- No `preview_data`, `file_tree`, or `preview_version` fields
- Has `user_message` with the triggering message
- `tool_calls` stored inline on `assistant_message`
- `node_execution_log` for graph node tracking

### 1.3 Chat Run Reducer

Handles the same canonical event types as skill_creator, mapped to the chat projection:

| Event Type | Projection Update |
|---|---|
| `user_message_added` | Set `user_message` |
| `assistant_message_started` | Initialize `assistant_message` with id |
| `content_delta` | Append to `assistant_message.content` |
| `tool_start` | Append to `assistant_message.tool_calls` (status: running) |
| `tool_end` | Update matching tool_call (status: completed, result) |
| `node_start` / `node_end` | Update `node_execution_log` |
| `interrupt` | Set `interrupt` |
| `error` | Set status to `failed`, record error |
| `done` | Set status to `completed` |

### 1.4 Database Changes

**No new migration required.** `agent_runs.agent_name` is `VARCHAR(100)` and `run_type` is `VARCHAR(100)`. Values `"chat"` / `"chat_turn"` are used directly.

---

## Section 2: Chat Protocol & WebSocket Changes

### 2.1 Extend `chat_protocol.py`

Add `"chat"` to supported extension kinds:

```python
SUPPORTED_EXTENSION_KINDS = {"skill_creator", "chat"}

@dataclass
class ParsedChatExtension:
    kind: Literal["chat"]
    run_id: str | None
```

`ParsedChatStartFrame.extension` type becomes `ParsedSkillCreatorExtension | ParsedChatExtension | None`.

### 2.2 New `ChatRunTurnCommand`

In `chat_commands.py`:

```python
@dataclass
class ChatRunTurnCommand(StandardChatTurnCommand):
    run_id: str | None = None
```

`ChatTurnCommand = StandardChatTurnCommand | SkillCreatorTurnCommand | ChatRunTurnCommand`

`build_command_from_parsed_frame()` routes to `ChatRunTurnCommand` when `extension.kind == "chat"`.

### 2.3 `ChatTurnExecutor` Changes

In `prepare_standard_turn`, detect `ChatRunTurnCommand`:

- Parse `run_id` into UUID
- Set `persist_on_disconnect = True` (when run_id is present)
- Start heartbeat task via `_run_persisted_run_heartbeat`
- Mirror events to `agent_run_events` via `_mirror_run_stream_event`

This logic is largely shared with `SkillCreatorTurnCommand` — extract a common helper for "persisted run" setup.

### 2.4 API Endpoint

Use the existing generic `POST /v1/runs` endpoint with `agent_name: "chat"`. No new alias endpoint needed (unlike skill-creator's convenience endpoint).

### 2.5 WS Frame Example

```json
{
  "type": "chat.start",
  "request_id": "uuid",
  "thread_id": "thread-uuid",
  "graph_id": "graph-uuid",
  "input": { "message": "Hello" },
  "extension": { "kind": "chat", "run_id": "run-uuid" }
}
```

---

## Section 3: Frontend Changes

### 3.1 Chat Send Message Flow

Current flow:
```
User clicks send → chat.start WS frame → stream events
```

New flow:
```
User clicks send
  → POST /v1/runs { agent_name: "chat", thread_id, graph_id, message }
  → Receive { run_id, thread_id, status }
  → Send chat.start WS frame with extension: { kind: "chat", run_id }
  → Subscribe /ws/runs (run_id) for Run Center updates
```

**Files to modify:**

| File | Change |
|---|---|
| `frontend/lib/ws/chat/types.ts` | Add `ChatExtension` type |
| `frontend/lib/ws/chat/chatWsClient.ts` | Support `ChatExtension` in `chat.start` frame |
| `frontend/app/chat/hooks/useChatWebSocket.ts` | Create run before sending WS frame in `sendMessage` |
| `frontend/app/chat/ChatProvider.tsx` | Add `run_id` to context state |

### 3.2 Run Center List Page

- Agent filter chips: "Chat" appears automatically (backend `GET /v1/runs/agents` returns registered agents)
- Chat run title: first 80 characters of user message
- Thread tag: display `thread_id` (truncated), clickable to filter same-thread runs

### 3.3 Run Center Detail Page — Chat Overview

New Chat-specific Overview tab content:

- **Message area**: User message + assistant reply (from projection `user_message` / `assistant_message`)
- **Tool calls**: Expandable list of tool invocations with inputs/outputs
- **Node execution log**: Timeline of graph node executions

Events tab and Snapshot tab remain unchanged (generic capabilities).

### 3.4 `buildRunHref` Update

```typescript
// frontend/lib/utils/runHelpers.ts
case "chat":
  return `/runs/${run.id}`;  // View within Run Center
```

---

## Section 4: Disconnect Recovery & Edge Cases

### 4.1 WS Disconnect Persistence

Identical to skill_creator:
- `ChatRunTurnCommand` tasks have `persist_on_disconnect = True`
- `ChatWsHandler._cancel_all_tasks()` skips persisted tasks
- Heartbeat writes `last_heartbeat_at` at `settings.run_heartbeat_interval_seconds`
- User reconnects via `/ws/runs` subscription to resume live stream

### 4.2 Chat Page Reconnect Recovery

When user refreshes `/chat`:

1. Query `GET /v1/runs/active?agent_name=chat&thread_id=xxx`
2. If active run exists → subscribe `/ws/runs`, restore UI from snapshot + event replay
3. If run completed → load from `conversations` + `messages` tables (existing flow)

### 4.3 Stale Run Recovery

Reuse existing `recover_stale_incomplete_runs()` — runs with heartbeat timeout are marked `FAILED`.

### 4.4 Concurrency Control

`ChatTaskSupervisor.is_thread_active()` already prevents concurrent turns on the same thread. Frontend disables send button while a turn is active.

### 4.5 Run Title Generation

Chat run `title` = first 80 characters of user message content. Truncated with `...` if longer.

---

## File Change Summary

### Backend (new files)

| File | Purpose |
|---|---|
| `backend/app/services/run_reducers/chat.py` | Chat agent registration + reducer + initial projection |

### Backend (modified files)

| File | Change |
|---|---|
| `backend/app/services/run_reducers/__init__.py` | Import and register chat reducer |
| `backend/app/websocket/chat_protocol.py` | Accept `extension.kind = "chat"`, add `ParsedChatExtension` |
| `backend/app/websocket/chat_commands.py` | Add `ChatRunTurnCommand`, update union type and routing |
| `backend/app/websocket/chat_turn_executor.py` | Extract shared persisted-run setup, handle `ChatRunTurnCommand` |

### Frontend (modified files)

| File | Change |
|---|---|
| `frontend/lib/ws/chat/types.ts` | Add `ChatExtension` type |
| `frontend/lib/ws/chat/chatWsClient.ts` | Support `ChatExtension` in `chat.start` frame |
| `frontend/app/chat/hooks/useChatWebSocket.ts` | Create run before WS frame, track `run_id` |
| `frontend/app/chat/ChatProvider.tsx` | Add `run_id` to context |
| `frontend/lib/utils/runHelpers.ts` | Add `"chat"` case to `buildRunHref` |
| `frontend/app/runs/[runId]/page.tsx` | Add Chat-specific Overview tab content |

### No new migrations required
