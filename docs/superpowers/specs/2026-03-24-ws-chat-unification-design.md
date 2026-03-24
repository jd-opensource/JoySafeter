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

Token passed as query param (WS does not support custom headers):

```
wss://<host>/ws/chat?token=<jwt>
```

The existing `authenticate_websocket(websocket)` utility reads this param. No changes required to auth layer.

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
        """Cancel task and stop LangGraph run."""

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

`_dispatch_stream_event()` yields strings in `"data: {...}\n\n"` format. The streaming task strips the `data: ` prefix, parses the JSON, injects `request_id`, and sends via `websocket.send_text()`.

```python
async for sse_str in _dispatch_stream_event(event, handler, state, file_emitter):
    payload_str = sse_str.lstrip("data:").strip()
    if payload_str:
        obj = json.loads(payload_str)
        obj["request_id"] = request_id
        await self._send(obj)
```

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

### HTTP endpoints to delete (from `chat.py`)

| Endpoint | Reason |
|---|---|
| `POST /v1/chat/stop` | Replaced by `{"type":"stop"}` WS frame |
| `POST /v1/chat/resume` | Replaced by `{"type":"resume"}` WS frame |
| `POST /v1/chat` (non-streaming) | Unused; no frontend caller (verify before deleting) |

> **Note:** Verify `POST /v1/chat` has no callers before deletion. `POST /v1/chat/stream` SSE endpoint is deleted after frontend migration is confirmed working.

---

## Frontend Design

### New file: `frontend/app/chat/hooks/useChatWebSocket.ts`

**Responsibilities:**
1. Open `WS /ws/chat?token=<jwt>` on mount; close on unmount.
2. Auto-reconnect with exponential backoff (reuse pattern from `useNotificationWebSocket`).
3. Expose `sendMessage(opts)` — generates `request_id`, sends `chat` frame, returns `request_id`.
4. Expose `stopMessage(threadId)` — sends `stop` frame (looks up `request_id` from active map).
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

**Connection lifecycle:** Opened in `ChatProvider` (already wraps the entire chat subtree), so the connection persists across conversation switches, mode changes, and navigating between threads.

**Token acquisition:** Use the same `getAccessToken()` utility used elsewhere in the app (currently used for HTTP Authorization header).

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
4. **Cutover:** Delete SSE endpoint, `useBackendChatStream`, old `POST /v1/chat/stop`, `POST /v1/chat/resume`.
5. **Cleanup:** Delete `chat_handler.py`, `connection_manager.py`, old `/ws/{session_id}` endpoint.

---

## Testing

- **Backend unit:** `chat_ws_handler.py` — mock WS, verify frame routing; verify task cancellation on `stop`; verify `WebSocketDisconnect` cleans up tasks.
- **Backend integration:** Connect real WS to `/ws/chat`; send `chat` frame; assert `content` events arrive; assert `done` arrives; assert DB has saved messages.
- **Frontend unit:** `useChatWebSocket` — mock `WebSocket`; assert `dispatch` called for each event type; assert reconnect fires after close.
- **E2E:** Full chat turn over WS; stop mid-stream; resume after interrupt.
