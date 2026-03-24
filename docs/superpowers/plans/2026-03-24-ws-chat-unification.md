# WS Chat Unification Implementation Plan

> Historical implementation plan. Final implementation on 2026-03-24 also migrated workspace execution and Skill Creator to `WS /ws/chat`, then removed the public `/v1/chat*` HTTP routes.

**Goal:** Replace the Chat page's SSE streaming path with a persistent `WS /ws/chat` connection, unify per-turn chat operations under request-scoped WS frames, and remove the dead legacy session chat websocket.

**Architecture:** Extract shared stream execution helpers from `backend/app/api/v1/chat.py`, add a connection-scoped `ChatWsHandler` that multiplexes turns by `request_id`, then move the frontend Chat subtree to a provider-owned WebSocket hook. Notification/copilot websockets stay unchanged. The final implementation also migrated workspace execution and Skill Creator, so `/v1/chat*` is no longer registered as a public API.

**Tech Stack:** FastAPI WebSocket, asyncio tasks, existing LangGraph `astream_events`, React hooks, browser `WebSocket`, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-24-ws-chat-unification-design.md`

**Verification:** Backend import/tests + frontend `tsc --noEmit`. Prefer targeted verification for touched modules if the full suite is too heavy.

---

## Scope Guardrails

- Migrate Chat page traffic from `POST /v1/chat/stream` to `WS /ws/chat`.
- Initial draft kept `POST /v1/chat/stop` and `POST /v1/chat/resume` for workspace-builder callers; this was later superseded by migrating those callers to WS as well.
- Delete legacy `WS /ws/{session_id}` and its implementation files only after removing the endpoint reference from `main.py`.
- Delete Chat-page SSE hook and SSE client helper once frontend is fully switched.

---

## Task 1: Backend Shared Execution Helpers

**Files:**
- Modify: `backend/app/api/v1/chat.py`

- [ ] Extract helper(s) for graph/context preparation so SSE and WS can share:
  - thread/conversation bootstrap
  - graph metadata lookup (`workspace_id`, display name)
  - initial context extraction from graph variables
  - graph creation for default-chat vs graph_id-backed runs
- [ ] Extract helper(s) for finalization so SSE and WS can share:
  - `task_manager.unregister_task`
  - `save_run_result`
  - backend cleanup
  - artifact manifest write
  - interrupt marker cleanup
- [ ] Keep existing HTTP behavior unchanged for `POST /v1/chat/stop` and `POST /v1/chat/resume`.

**Verification**
- [ ] `python -m py_compile backend/app/api/v1/chat.py`

---

## Task 2: Add `ChatWsHandler` And WS Endpoint

**Files:**
- Create: `backend/app/websocket/chat_ws_handler.py`
- Modify: `backend/app/main.py`
- Delete: `backend/app/websocket/chat_handler.py`
- Delete: `backend/app/websocket/connection_manager.py`

- [ ] Implement `ChatWsHandler` with:
  - authenticated persistent connection
  - frame routing for `chat`, `resume`, `stop`, `ping`
  - `_tasks: request_id -> (thread_id, asyncio.Task)` tracking
  - thread-level concurrency guard
  - safe `None` filtering when converting SSE strings to WS JSON envelopes
  - disconnect cleanup for all in-flight tasks
- [ ] Register `@app.websocket("/ws/chat")` in `main.py`.
- [ ] Remove legacy `@app.websocket("/ws/{session_id}")` endpoint and stale imports.

**Verification**
- [ ] `python -m py_compile backend/app/main.py backend/app/websocket/chat_ws_handler.py`

---

## Task 3: Frontend WS Hook And Provider Migration

**Files:**
- Create: `frontend/app/chat/hooks/useChatWebSocket.ts`
- Modify: `frontend/app/chat/ChatProvider.tsx`
- Modify: `frontend/app/chat/ChatLayout.tsx`
- Modify: `frontend/services/chatBackend.ts`
- Delete: `frontend/app/chat/hooks/useBackendChatStream.ts`

- [ ] Move chat event type definitions into a reusable module or keep them in `chatBackend.ts` while removing `streamChat()`.
- [ ] Implement provider-owned `useChatWebSocket` with:
  - single persistent `/ws/chat` connection
  - reconnect/backoff
  - request tracking by `request_id`
  - reverse lookup `threadId -> requestId` for stop
  - `done` / `error` driven `STREAM_DONE`
  - `4001` auth-close handling
- [ ] Extend `ChatStreamContext` to expose:
  - `isConnected`
  - `sendMessage`
  - `stopMessage`
  - `resumeChat`
- [ ] Update `ChatLayout.tsx` to consume WS functions from context and remove direct SSE hook usage.
- [ ] Delete `useBackendChatStream.ts` after references are removed.

**Verification**
- [ ] `cd frontend && npx tsc --noEmit`

---

## Task 4: Cutover Cleanup

**Files:**
- Modify: `backend/app/api/v1/chat.py`

- [ ] Remove `POST /v1/chat/stream` SSE endpoint once the frontend no longer references it.
- [ ] Keep `POST /v1/chat` only if there are live callers; otherwise remove it in the same cleanup batch if unused.
- [ ] Run a repo-wide search to confirm no stale Chat-page SSE references remain.

**Verification**
- [ ] `rg -n "chat/stream|useBackendChatStream|streamChat\\(" frontend backend -S`

---

## Task 5: Final Verification

- [ ] Run backend targeted tests if present, otherwise at least import/compile verification for touched modules.
- [ ] Run frontend type-check.
- [ ] Update planning/progress files with outcomes and residual risks.

## Final Outcome

- `WS /ws/chat` is the active transport for Chat page, Skill Creator, and workspace execution flows.
- Legacy `WS /ws/{session_id}` plus its implementation files were deleted.
- Public `/v1/chat`, `/v1/chat/stream`, `/v1/chat/stop`, and `/v1/chat/resume` are no longer registered.
- `backend/app/api/v1/chat.py` remains as an internal helper module reused by `chat_ws_handler.py`.
