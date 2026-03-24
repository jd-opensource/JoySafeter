# WS Chat Unification Design

## Goal

Replace the current SSE-based chat streaming (`POST /v1/chat/stream`) with a persistent WebSocket connection, unify all real-time channels under a coherent WS architecture, and delete the orphaned legacy WS chat handler.

## Architecture

A single persistent WS connection (`/ws/chat`) is established per user when the Chat page mounts. All chat turns (new thread, existing thread, resume-after-interrupt) are multiplexed over that connection using a `request_id`. Stop and resume operations are sent as frames on the same connection, eliminating the separate `POST /v1/chat/stop` and `POST /v1/chat/resume` HTTP endpoints. The three other WS channels (notifications, copilot, legacy session chat) are addressed independently: notifications and copilot are kept unchanged; the legacy session chat endpoint is deleted as dead code.

## Tech Stack

- **Backend:** FastAPI WebSocket, asyncio Tasks, existing LangGraph `astream_events` pipeline, existing `task_manager`, existing `authenticate_websocket`
- **Frontend:** Browser `WebSocket` API, React hooks, existing `useChatReducer` dispatch

---

## WS Endpoint Inventory (after migration)

| Endpoint | Handler | Status |
|---|---|---|
| `WS /ws/chat` | `chat_ws_handler.py` (new) | **New** |
| `WS /ws/notifications` | `notification_manager.py` | Keep |
| `WS /ws/copilot/{session_id}` | `copilot_handler.py` | Keep |
| `WS /ws/{session_id}` | `chat_handler.py` | **Delete** (no frontend callers) |

---

## Message Protocol

### Authentication

The existing `authenticate_websocket(websocket)` first tries five cookie names; it falls back to the `?token=` query param only if all cookies are absent. For same-origin browser connections, the existing auth cookie is used automatically — no extra token-passing logic needed. The `?token=` fallback exists for non-browser or cross-origin clients.

```
# Browser (same-origin): cookies handled automatically by the browser
wss://<host>/ws/chat

# Non-browser / cross-origin fallback
wss://<host>/ws/chat?token=<jwt>
```

No changes required to the auth layer.

### Client → Server frames

All frames are JSON objects sent via `websocket.send_text(json.dumps(...))`.

```jsonc
// Start a new chat turn
{
  "type": "chat",
  "request_id": "<uuid>",      // client-generated; used to correlate all server events for this turn
  "thread_id": "<str|null>",   // null = new conversation
  "graph_id": "<uuid|null>",
  "message": "<str>",
  "metadata": {}               // files, edit_skill_id, etc. — same as current SSE payload
}

// Cancel a running turn
{
  "type": "stop",
  "request_id": "<uuid>"       // request_id of the turn to stop
}

// Resume after interrupt
{
  "type": "resume",
  "request_id": "<uuid>",      // new request_id for this resume turn
  "thread_id": "<str>",
  "command": { "update": {}, "goto": "<str|null>" }
}

// Keepalive
{ "type": "ping" }
```

### Server → Client frames

Same event envelope as the current SSE payload (`StreamEventEnvelope` in `chatBackend.ts`), but:
- No `data: ` SSE framing
- `request_id` field added to every event for multiplexing

```jsonc
{
  "type": "content" | "tool_start" | "tool_end" | "node_start" | "node_end" |
          "status" | "error" | "done" | "thread_id" | "interrupt" |
          "file_event" | "command" | "route_decision" | ... ,
  "request_id": "<uuid>",
  "thread_id": "<str>",
  "run_id": "<str>",
  "node_name": "<str>",
  "timestamp": <number>,
  "data": {}
}

// Keepalive response
{ "type": "pong" }

// Protocol-level error (e.g. bad frame format, auth expired)
{ "type": "ws_error", "message": "<str>" }
```

---

## Backend Design

### New file: `backend/app/websocket/chat_ws_handler.py`

**Responsibilities:**
1. Accept an authenticated WS connection; hold it open until client disconnects.
2. Read incoming frames in a loop and dispatch by `type`.
3. For `chat` and `resume`: start an `asyncio.Task` that runs the existing LangGraph pipeline and streams events back over the WS. Register the task with `task_manager` keyed by `thread_id` (same as today).
4. For `stop`: call `task_manager.stop_task(thread_id)` and cancel the corresponding task. The task's `finally` block sends a `done` frame.
5. For `ping`: immediately send `pong`.
6. On any `WebSocketDisconnect`: cancel all in-flight tasks for this connection, then exit.

**Key class: `ChatWsHandler`**

```python
class ChatWsHandler:
    def __init__(self, user_id: str, websocket: WebSocket):
        self.user_id = user_id
        self.websocket = websocket
        # maps request_id → (thread_id, asyncio.Task)
        self._tasks: dict[str, tuple[str, asyncio.Task]] = {}

    async def run(self) -> None:
        """Main loop — reads frames until disconnect."""

    async def _handle_chat(self, frame: dict) -> None:
        """Validate frame, start streaming Task."""

    async def _handle_stop(self, frame: dict) -> None:
        """
        Cancel task and stop LangGraph run.
        If request_id is not in _tasks (turn already finished), silently ignore.
        Must NOT raise — an unhandled exception here disconnects the WS.

        Implementation must do:
            entry = self._tasks.get(frame.get("request_id"))
            if entry is None:
                return   # already done, ignore
            thread_id, task = entry
            await task_manager.stop_task(thread_id)
            task.cancel()
        """

    async def _handle_resume(self, frame: dict) -> None:
        """Start resume streaming Task."""

    async def _stream_to_ws(
        self,
        request_id: str,
        thread_id: str,
        graph,
        config,
        input_messages,
        file_emitter,
    ) -> None:
        """
        Iterate astream_events, call _dispatch_stream_event() (imported from chat.py),
        and send each SSE string as a WS frame after stripping 'data: ' prefix and
        injecting request_id.
        """

    async def _send(self, event: dict) -> None:
        """Safe send with disconnect handling."""
```

**Reuse strategy:** `_dispatch_stream_event()` and all helper functions (`save_user_message`, `save_assistant_message`, `_clear_interrupt_marker`, `_enrich_message`, `get_or_create_conversation`, `get_user_config`, `findOrCreateGraph`) are imported from `chat.py` unchanged. The only new logic is the WS framing layer.

**SSE → WS event conversion:**

`_dispatch_stream_event()` yields strings in `"data: {...}\n\n"` format, but several handler paths (e.g. `handle_chat_model_stream` when there is no delta, exception paths in `handle_chat_model_start`) return `None`, which is then yielded as `None`. The conversion loop **must** guard against `None` before stripping:

```python
async for sse_str in _dispatch_stream_event(event, handler, state, file_emitter):
    if not sse_str:          # guard: None or empty string → skip
        continue
    payload_str = sse_str.lstrip("data:").strip()
    if payload_str:
        obj = json.loads(payload_str)
        obj["request_id"] = request_id
        await self._send(obj)
```

**Invariant:** every non-`None` value yielded by `_dispatch_stream_event` is a string of the form `"data: <json>\n\n"`. The `.lstrip("data:").strip()` pattern is correct for this format. The `on_chain_end` list path adds an extra `\n\n` via `event_str.strip() + "\n\n"`, but the outer `.strip()` call in the conversion loop normalises this harmlessly.

### `main.py` changes

```python
# Add
from app.websocket.chat_ws_handler import ChatWsHandler

@app.websocket("/ws/chat")
async def chat_websocket_endpoint(websocket: WebSocket):
    is_authenticated, user_id = await authenticate_websocket(websocket)
    if not is_authenticated or not user_id:
        await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, ...)
        return
    await websocket.accept()
    handler = ChatWsHandler(user_id=str(user_id), websocket=websocket)
    await handler.run()

# Delete
@app.websocket("/ws/{session_id}")   # ← remove
```

### Files to delete

| File | Reason |
|---|---|
| `backend/app/websocket/chat_handler.py` | No frontend callers; replaced by `chat_ws_handler.py` |
| `backend/app/websocket/connection_manager.py` | Only used by deleted `chat_handler.py` |

### HTTP endpoints — deletion scope

> **⚠️ IMPORTANT:** `POST /v1/chat/stop` and `POST /v1/chat/resume` have callers **outside** the chat page:
> - `frontend/app/workspace/[workspaceId]/[agentId]/stores/execution/executionStore.ts` calls `apiPost('chat/stop', ...)`
> - `frontend/app/workspace/[workspaceId]/[agentId]/services/commandService.ts` calls `apiStream('chat/resume', ...)`
>
> These workspace-agent callers use HTTP and are **not** affected by the WS migration. **Do not delete these endpoints until the workspace callers are also migrated or removed.**

| Endpoint | Action | Condition |
|---|---|---|
| `POST /v1/chat/stop` | Keep; also accept WS `stop` frame | Keep HTTP until workspace callers migrated |
| `POST /v1/chat/resume` | Keep; also accept WS `resume` frame | Keep HTTP until workspace callers migrated |
| `POST /v1/chat/stream` (SSE) | Delete after frontend WS migration verified | Chat-page only |
| `POST /v1/chat` (non-streaming) | Verify no callers, then delete | Likely unused |

---

## Frontend Design

### New file: `frontend/app/chat/hooks/useChatWebSocket.ts`

**Responsibilities:**
1. Open `WS /ws/chat?token=<jwt>` on mount; close on unmount.
2. Auto-reconnect with exponential backoff (reuse pattern from `useNotificationWebSocket`).
3. Expose `sendMessage(opts)` — generates `request_id`, sends `chat` frame, returns `request_id`.
4. Expose `stopMessage(threadId)` — performs a `threadId → requestId` reverse lookup using an internal `activeByThread: Map<threadId, requestId>` map (maintained alongside `activeRequests`), then sends `{"type":"stop", "request_id": ...}`. If no active request exists for that thread, this is a no-op. The map stores only the most recent `request_id` per `thread_id`, so when a new turn starts on an existing thread the map entry is updated and the previous (already completed) `request_id` is discarded.
5. Expose `resumeChat(opts)` — sends `resume` frame.
6. On incoming message: parse JSON, dispatch to `useChatReducer` using the exact same event-handling logic currently in `useBackendChatStream.ts` `onEvent` callback.

**Interface:**

```typescript
interface UseChatWebSocketReturn {
  isConnected: boolean
  sendMessage: (opts: SendMessageOpts) => Promise<{ requestId: string }>
  stopMessage: (threadId: string) => void
  resumeChat: (opts: ResumeOpts) => Promise<{ requestId: string }>
}
```

**Concurrent turn policy:** If a `chat` frame arrives for a `thread_id` that already has an in-flight task, the handler sends `{"type":"ws_error", "message":"turn already in progress for thread_id"}` and does not start a second task. This prevents `task_manager.register_task(thread_id, ...)` from silently overwriting the first task entry. The `_tasks` map should be checked both by `request_id` (for stop) and by `thread_id` (for concurrency guard).

```python
# In _handle_chat:
active_thread_ids = {tid for (tid, _) in self._tasks.values()}
if thread_id and thread_id in active_thread_ids:
    await self._send({"type": "ws_error", "message": "turn already in progress"})
    return
```

**`STREAM_DONE` dispatch (frontend):** In `useBackendChatStream` the `STREAM_DONE` action is dispatched in a `finally` block wrapping the entire SSE promise — not in response to the `done` event (which is a no-op). In `useChatWebSocket` there is no wrapping promise per turn; `STREAM_DONE` must be dispatched when the server sends `{"type": "done", "request_id": ...}`, and also on `{"type": "error", ...}` (error ends the turn). The `onEvent` handler must be updated accordingly:

```typescript
if (type === 'done') {
  dispatch({ type: 'STREAM_DONE', messageId: activeRequests[request_id].aiMsgId })
  delete activeRequests[request_id]
  return
}
if (type === 'error') {
  // dispatch error, then finalize
  dispatch({ type: 'STREAM_ERROR', error: errorData.message })
  dispatch({ type: 'STREAM_DONE', messageId: activeRequests[request_id]?.aiMsgId })
  delete activeRequests[request_id]
  return
}
```

**Connection lifecycle:** Opened in `ChatProvider` (already wraps the entire chat subtree), so the connection persists across conversation switches, mode changes, and navigating between threads.

### `ChatProvider.tsx` changes

- Instantiate `useChatWebSocket` at this level (not inside `ChatHome` or `ChatLayout`).
- Add `isConnected`, `sendMessage`, `stopMessage`, `resumeChat` to the existing streaming context (`ChatStreamContext`).

### `ChatLayout.tsx` / `ChatHome.tsx` changes

- Replace `useBackendChatStream` calls with values from streaming context.
- `handleSubmit` calls `sendMessage(opts)` instead of the SSE `sendMessage`.
- Stop button calls `stopMessage(threadId)`.
- Resume calls `resumeChat(opts)`.

### Files to delete

| File | Reason |
|---|---|
| `frontend/app/chat/hooks/useBackendChatStream.ts` | Replaced by `useChatWebSocket.ts` |
| `frontend/services/chatBackend.ts` — `streamChat()` function and SSE parsing | Replaced; type definitions (`ChatStreamEvent`, `StreamEventEnvelope`, etc.) move to `frontend/types/chat-events.ts` |

---

## Error Handling

| Scenario | Behavior |
|---|---|
| WS connect fails | `isConnected=false`; auto-reconnect with backoff; UI shows "Reconnecting…" |
| Auth expired mid-session | Server closes WS with code 4001; frontend redirects to login |
| LangGraph error during streaming | Server sends `{"type":"error", "request_id":...}`; frontend dispatches `STREAM_ERROR`; `done` frame follows |
| Client disconnects mid-stream | `ChatWsHandler.run()` catches `WebSocketDisconnect`; cancels all in-flight tasks; `task_manager` cleanup runs in task `finally` |
| `stop` frame arrives after task completes | Ignored (task no longer in `_tasks` map) |

---

## Migration Sequence

1. **Backend:** Implement `chat_ws_handler.py`; add `/ws/chat` endpoint; keep SSE endpoint live.
2. **Frontend:** Implement `useChatWebSocket`; wire into `ChatProvider`; feature-flag or replace `useBackendChatStream`.
3. **Verify:** Both SSE and WS paths work end-to-end in staging.
4. **Cutover:** Delete `POST /v1/chat/stream` SSE endpoint and `useBackendChatStream`. **Do not yet delete `POST /v1/chat/stop` or `POST /v1/chat/resume`** — they still serve workspace callers (see HTTP endpoint table above).
5. **Workspace migration:** Migrate `executionStore.ts` and `commandService.ts` to use WS frames or dedicated endpoints.
6. **Cleanup:** Delete `POST /v1/chat/stop`, `POST /v1/chat/resume`, `chat_handler.py`, `connection_manager.py`, old `/ws/{session_id}` endpoint.

---

## Testing

- **Backend unit:** `chat_ws_handler.py` — mock WS, verify frame routing; verify task cancellation on `stop`; verify `WebSocketDisconnect` cleans up tasks.
- **Backend integration:** Connect real WS to `/ws/chat`; send `chat` frame; assert `content` events arrive; assert `done` arrives; assert DB has saved messages.
- **Frontend unit:** `useChatWebSocket` — mock `WebSocket`; assert `dispatch` called for each event type; assert reconnect fires after close.
- **E2E:** Full chat turn over WS; stop mid-stream; resume after interrupt.
