# Phase 3: Copilot Run Center Integration

## Goal

Unify Copilot's session-based persistence (Redis Pub/Sub + ephemeral keys) into the shared Agent Run Center model. Copilot execution moves from a standalone BackgroundTask + `/ws/copilot` endpoint into the Chat WS turn executor, using `agent_run_events` for persistence and `/ws/runs` for observation. The existing `copilot_chats` table and Redis Pub/Sub mechanism are removed entirely.

## Architecture Overview

After this change, Copilot follows the same pattern as Chat and Skill Creator:

```
Frontend                         Backend
────────                         ───────
runService.createRun()  ──POST──►  agent_runs row created
      │
getChatWsClient().sendChat({     ChatWsHandler receives chat.start
  extension: {                   ├─ _parse_extension → ParsedCopilotExtension
    kind: "copilot",             ├─ build_command → CopilotTurnCommand
    run_id, graph_context,       ├─ prepare_standard_turn → PreparedStandardTurn
    conversation_history, mode   └─ execute_copilot_turn:
  }                                   ├─ CopilotService._get_copilot_stream()
})                                    ├─ for event in stream:
      │                               │   _emit_event() → WS + agent_run_events
      │                               ├─ _persist_graph_from_actions()
      ▼                               └─ emit "done"
onEvent callback ◄──── /ws/chat ─────┘
      │
      ▼
/ws/runs subscription ◄── snapshot + event replay (reconnect)
```

Three systems removed:
- `/ws/copilot/{session_id}` WebSocket endpoint
- Redis Pub/Sub (`copilot:session:*` keys)
- `copilot_chats` table (no dual-write, no backward compat)

## Detailed Design

### 1. Extension Protocol

#### WS Frame

```json
{
  "type": "chat.start",
  "request_id": "req-uuid",
  "thread_id": null,
  "graph_id": "graph-uuid",
  "input": { "message": "Build a RAG pipeline", "model": "anthropic:claude-3-7-sonnet" },
  "extension": {
    "kind": "copilot",
    "run_id": "run-uuid",
    "graph_context": { "nodes": [], "edges": [] },
    "conversation_history": [{"role": "user", "content": "..."}, ...],
    "mode": "deepagents"
  }
}
```

`graph_context` and `conversation_history` live in the extension (not input/metadata) because they are Copilot-specific payloads that do not belong in the generic chat input.

#### chat_protocol.py

New dataclass:

```python
@dataclass(frozen=True)
class ParsedCopilotExtension:
    kind: Literal["copilot"]
    run_id: str | None
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]]
    mode: str  # "standard" | "deepagents"
```

`_parse_extension` adds a `kind == "copilot"` branch that extracts `graph_context` (required dict), `conversation_history` (optional list, default `[]`), and `mode` (optional string, default `"deepagents"`).

`ParsedChatStartFrame.extension` type widens to include `ParsedCopilotExtension`.

#### chat_commands.py

New command:

```python
@dataclass(frozen=True)
class CopilotTurnCommand(StandardChatTurnCommand):
    run_id: str | None = None
    graph_context: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "deepagents"
```

`ChatTurnCommand` union type adds `CopilotTurnCommand`.

`build_command_from_parsed_frame` adds `isinstance(extension, ParsedCopilotExtension)` branch before the existing chat/skill_creator branches.

### 2. Copilot Reducer & Projection

#### Event Vocabulary

| Copilot stream event | run event_type | payload |
|---|---|---|
| `status` | `status` | `{stage, message}` |
| `content` | `content_delta` | `{delta}` |
| `thought_step` | `thought_step` | `{step: {index, content}}` |
| `tool_call` | `tool_call` | `{tool, input}` |
| `tool_result` | `tool_result` | `{action: {type, payload, reasoning}}` |
| `result` | `result` | `{message, actions[], batch?}` |
| `error` | `error` | `{message, code}` |
| `done` | `done` | `{}` |

Note: `content` is stored as `content_delta` in run events (aligning with chat reducer naming), but emitted over WS as the original `content` type so the frontend callback can discriminate.

#### Initial Projection

```python
def make_initial_projection() -> dict:
    return {
        "run_type": "copilot_turn",
        "status": "running",
        "stage": None,
        "content": "",
        "thought_steps": [],
        "tool_calls": [],
        "tool_results": [],
        "result_message": None,
        "result_actions": [],
        "error": None,
        "graph_id": None,
        "mode": None,
    }
```

#### Reducer Logic

```python
def apply_copilot_event(projection, *, event_type, payload, status) -> dict:
    p = copy.deepcopy(projection)

    if event_type == "run_initialized":
        p["graph_id"] = payload.get("graph_id")
        p["mode"] = payload.get("mode")
        return p

    if event_type == "status":
        p["stage"] = payload.get("stage")
        return p

    if event_type == "content_delta":
        p["content"] += payload.get("delta", "")
        return p

    if event_type == "thought_step":
        step = payload.get("step")
        if step:
            p["thought_steps"].append(step)
        return p

    if event_type == "tool_call":
        p["tool_calls"].append({
            "tool": payload.get("tool", ""),
            "input": payload.get("input", {}),
        })
        return p

    if event_type == "tool_result":
        action = payload.get("action")
        if action:
            p["tool_results"].append(action)
        return p

    if event_type == "result":
        p["result_message"] = payload.get("message", "")
        p["result_actions"] = payload.get("actions", [])
        return p

    if event_type == "error":
        p["status"] = "failed"
        p["error"] = payload.get("message")
        return p

    if event_type == "done":
        if p["status"] != "failed":
            p["status"] = "completed"
        return p

    return p
```

#### AgentRegistry

```python
agent_registry.register(
    AgentDefinition(
        agent_name="copilot",
        display_name="Copilot",
        run_type="copilot_turn",
        reducer=apply_copilot_event,
        make_initial_projection=copilot_make_initial_projection,
    )
)
```

### 3. Backend Execution Flow

#### execute_copilot_turn

New method on `ChatTurnExecutor`:

```
execute_copilot_turn(request_id, payload, graph_context, conversation_history, mode):
    1. set_trace_id(request_id)
    2. Read agent_run_id, tolerate_disconnect from task_supervisor
    3. Generate assistant_message_id
    4. Mark run RUNNING + start heartbeat
    5. Emit "accepted" event
    6. Open DB session, get user credentials (get_user_config)
    7. Create CopilotService instance
    8. Call service._get_copilot_stream(prompt, graph_context, history, mode, graph_id)
    9. Consume stream:
       for event in stream:
           # Normalize to standard WS event format
           ws_event = {
               "type": event["type"],
               "thread_id": thread_id,
               "node_name": "copilot",
               "timestamp": int(time.time() * 1000),
               "data": event,
           }
           await handler._emit_event(ws_event, request_id, ...)
           # Collect thought_steps, tool_calls, final_message, final_actions
   10. _persist_graph_from_actions(graph_id, final_actions)
   11. Emit "done"

   except CancelledError → emit "done", raise
   except Exception → emit "error" + "done"
   finally → _finalize_task(...)
```

Events are emitted directly via `handler._emit_event()` (approach A) rather than going through SSE format_sse / parse round-trip. Each copilot event dict is placed under the `data` key of the standard WS event envelope.

#### Turn Executor Integration

`ChatTurnExecutor.prepare_standard_turn` adds:

```python
elif isinstance(command, CopilotTurnCommand):
    run_id = self._parse_uuid(command.run_id)
    persist_on_disconnect = run_id is not None
```

`ChatTurnExecutor.run_standard_turn` or `ChatWsHandler._handle_standard_turn` routes to `execute_copilot_turn` when the command is `CopilotTurnCommand`.

#### Relationship to Existing Code

- `CopilotService._get_copilot_stream` — **unchanged**, the core engine entry point
- `CopilotService._persist_graph_from_actions` — **unchanged**, called after stream completes
- `CopilotService.generate_actions_async` — **deleted** (Redis Pub/Sub path)
- `CopilotService._consume_stream_and_publish_to_redis` — **deleted**
- `CopilotService._persist_conversation` / `save_messages` / `save_conversation_from_stream` — **deleted** (no copilot_chats writes)
- `POST /copilot/actions` (sync path) — **unchanged**, standalone non-streaming endpoint
- `POST /copilot/actions/create` — **deleted** (replaced by WS chat.start)
- `GET /copilot/sessions/{session_id}` — **deleted** (replaced by run snapshot)

### 4. Frontend Changes

#### Scope

Transport + persistence only. All Copilot UI components remain unchanged: `CopilotChat`, `CopilotStreaming`, `CopilotInput`, `CopilotPanel`, `CopilotErrorBoundary`.

#### New Types

```typescript
// lib/ws/chat/types.ts
interface CopilotExtension {
  kind: 'copilot'
  runId?: string | null
  graphContext: Record<string, unknown>
  conversationHistory: Array<Record<string, unknown>>
  mode: string
}
```

`ChatSendParams.extension` type widens to include `CopilotExtension`.

#### serializeExtension

```typescript
if (extension.kind === 'copilot') {
  return {
    kind: extension.kind,
    run_id: extension.runId ?? null,
    graph_context: extension.graphContext,
    conversation_history: extension.conversationHistory,
    mode: extension.mode,
  }
}
```

#### Send Flow (New)

```
CopilotInput → handleSend → useCopilotActions.handleSendWithInput:
  1. runService.createRun({ agent_name: "copilot", graph_id, message })
     → returns run_id
  2. getChatWsClient().sendChat({
       input: { message, model },
       graphId,
       extension: {
         kind: "copilot",
         runId: run_id,
         graphContext: getGraphContext(),
         conversationHistory: convertConversationHistory(messages),
         mode: selectedMode,
       },
       onEvent: handleCopilotEvent,
       onAccepted: (evt) => { /* save thread_id if needed */ },
     })
  3. Save run_id to localStorage as copilot_run_{graphId}
```

#### Event Reception

`handleCopilotEvent` receives standard `ChatStreamEvent` from the `onEvent` callback. The copilot payload is nested under `evt.data`:

```typescript
function handleCopilotEvent(evt: ChatStreamEvent) {
  const data = evt.data as Record<string, unknown>
  const type = data?.type as string

  switch (type) {
    case 'status':       onStatus(data.stage, data.message); break
    case 'content':      onContent(data.content); break
    case 'thought_step': onThoughtStep(data.step); break
    case 'tool_call':    onToolCall(data.tool, data.input); break
    case 'tool_result':  onToolResult(data.action); break
    case 'result':       onResult({ message: data.message, actions: data.actions }); break
    case 'error':        onError(data.message, data.code); break
  }
}
```

Existing `onStatus / onContent / onResult / onError / onDone` callbacks and all UI components remain unchanged.

#### Session Recovery (New)

Old: `localStorage(session_id)` → `copilotService.getSession()` → only recovers final `result`.

New:
1. Page load → `localStorage` reads `copilot_run_{graphId}` → gets `run_id`
2. `runService.getRunSnapshot(run_id)` → full projection (content, thought_steps, tool_calls, result_actions)
3. If run is active → subscribe `/ws/runs` for `run_id`, replay from `after_seq`
4. If run is completed/failed → restore final state from projection

Full-fidelity recovery: streaming content, thought_steps, tool_calls all preserved across page refresh.

#### Stop Flow

`handleStop` calls `getChatWsClient().stopByRequestId(requestId)` (sends `chat.stop` frame). Same mechanism as Chat/Skill Creator.

#### Files Changed

| File | Change |
|---|---|
| `lib/ws/chat/types.ts` | Add `CopilotExtension` interface, widen `ChatSendParams.extension` |
| `lib/ws/chat/chatWsClient.ts` | Add `copilot` branch in `serializeExtension` |
| `hooks/copilot/useCopilotSession.ts` | `session_id` → `run_id`, key → `copilot_run_{graphId}` |
| `app/workspace/.../hooks/useCopilotActions.ts` | Replace `copilotService.createCopilotTask` → `runService.createRun` + `sendChat` |
| `app/workspace/.../hooks/useCopilotWebSocketHandler.ts` | Receive events from chat WS `onEvent` callback |
| `app/workspace/.../hooks/useCopilotEffects.ts` | Recovery via `runService` + `/ws/runs` subscription |
| `services/copilotService.ts` | Remove `createCopilotTask`, `getSession` |

#### Files Deleted

| File | Reason |
|---|---|
| `hooks/use-copilot-websocket.ts` | Replaced by shared chat WS client |

### 5. History API Rewrite

#### GET /{graph_id}/copilot/history

Rewritten to query `agent_runs`:

```python
async def get_copilot_history(graph_id, user_id, db):
    runs = await agent_run_repo.list_recent_runs_for_user(
        user_id=user_id,
        agent_name="copilot",
        limit=100,
    )
    # Filter to matching graph_id
    runs = [r for r in runs if str(r.graph_id) == str(graph_id)]
    # Build messages from run snapshots
    messages = []
    for run in reversed(runs):  # oldest first
        snapshot = await agent_run_repo.get_snapshot(run.id)
        if not snapshot or not snapshot.projection:
            continue
        p = snapshot.projection
        # User message
        messages.append({
            "role": "user",
            "content": run.title or "",
            "created_at": run.created_at.isoformat(),
        })
        # Assistant message
        messages.append({
            "role": "assistant",
            "content": p.get("result_message") or p.get("content", ""),
            "created_at": run.updated_at.isoformat(),
            "actions": p.get("result_actions", []),
            "thought_steps": p.get("thought_steps", []),
            "tool_calls": p.get("tool_calls", []),
        })
    return {"graph_id": str(graph_id), "messages": messages}
```

Response format matches existing `CopilotHistoryResponse` so frontend `useCopilotHistory` works unchanged.

#### DELETE /{graph_id}/copilot/history

Soft-delete: marks matching copilot runs as hidden (add a `hidden` flag or simply delete the runs). Implementation detail to be decided during planning.

### 6. Run Center Visibility

#### runHelpers.ts

```typescript
case 'copilot_turn':
  return `/runs/${encodeURIComponent(run.run_id)}`
```

#### CopilotTurnOverview Component

New component in `/runs/[runId]/page.tsx` for `run_type === 'copilot_turn'`:

- Stage indicator
- Streaming content
- Thought steps (collapsible)
- Tool calls (collapsible)
- Result message + actions list
- Error display

### 7. Deleted Code

#### Backend

| Target | Action |
|---|---|
| `app/websocket/copilot_handler.py` | Delete entire file |
| `app/main.py` `/ws/copilot` route | Delete route registration |
| `app/repositories/copilot_chat_repository.py` | Delete entire file |
| `app/models/chat.py` `CopilotChat` class | Delete model |
| `app/core/redis.py` copilot methods | Delete ~12 methods and key constants |
| `app/api/v1/graphs.py` `POST /copilot/actions/create` | Delete endpoint |
| `app/api/v1/graphs.py` `GET /copilot/sessions/{session_id}` | Delete endpoint |
| `app/services/copilot_service.py` Redis/persist methods | Delete `generate_actions_async`, `_consume_stream_and_publish_to_redis`, `_persist_conversation`, `save_messages`, `save_conversation_from_stream` |

#### Frontend

| Target | Action |
|---|---|
| `hooks/use-copilot-websocket.ts` | Delete entire file |
| `services/copilotService.ts` `createCopilotTask`, `getSession` | Delete methods |

### 8. Testing

#### Backend Unit Tests

| Test file | Coverage |
|---|---|
| `test_copilot_run_reducer.py` | All event types: status, content_delta, thought_step, tool_call, tool_result, result, error, done, run_initialized (~10 cases) |
| `test_chat_protocol_copilot_extension.py` | Parse `kind="copilot"` with graph_context, mode, conversation_history; reject missing graph_context |
| `test_chat_commands_copilot.py` | `CopilotTurnCommand` construction + regression for chat/skill_creator paths |
| `test_copilot_history_from_runs.py` | History endpoint correctly assembles response from agent_run snapshots |

#### Frontend

- TypeScript compilation passes
- `serializeExtension` correctly serializes `copilot` kind

#### Manual Verification

1. Send copilot message → full event stream (status → content → thought_step → tool_call → result → done)
2. Page refresh during execution → full state recovery from run snapshot + event replay
3. Run Center `/runs` → copilot runs visible with correct overview
4. `GET copilot/history` → returns history from run snapshots
5. Stop mid-execution → clean interruption
