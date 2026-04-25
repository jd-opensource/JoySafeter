# Global Chat — Developer Debug Chat System Design

> Date: 2026-04-25
> Status: Draft
> Scope: Full-stack (backend endpoint + deletion + frontend component system)

## 1. Problem Statement

The current `AgentChatTab` has structural issues:

1. **Hardcoded context** — binds to `agentId`, router navigation, workspace resolution; impossible to reuse
2. **No file capability** — `ChatRequest` accepts plain text only
3. **Primitive input** — single-line `<Input>`, no file upload, no file preview
4. **Redundant storage layer** — `ThreadMessage` is a read projection of `ExecutionEvent`, duplicating the source of truth with a weaker schema. `MessageProjectionSubscriber` exists only to maintain this projection.

## 2. Architecture Foundation

The new execution event architecture establishes:

- **`ExecutionEvent` is the single source of truth** for all execution content
- Every conversation turn = `AgentRun → Execution → N ExecutionEvents`
- `Thread` groups multiple turns (runs) for a given Agent
- Data flow: `Thread → AgentRuns → Executions → ExecutionEvents`

The chat UI is a **view layer over execution events** — the same data source that Graph Builder's ExecutionTimeline renders, but with a conversation-style presentation. No separate message storage exists or should exist.

## 3. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Core positioning | Developer debug tool | Testing agents, inspecting execution, uploading test files |
| Embedding model | Replace existing `AgentChatTab` | Reusable component via props, not route-coupled |
| Message storage | None — ExecutionEvent IS the message | Source of truth already exists; delete the redundant projection |
| File input | Extend `USER_MESSAGE` event payload | Attachments are metadata on the user's input event |
| File preview | Upload (sandbox files) + artifact (Artifact table) | Both already stored; frontend renders by MIME type |
| Streaming | Reuse WS `/ws/executions` subscription | Already exists, no changes needed |
| History | New aggregation endpoint over existing tables | One JOIN query, zero new tables |

## 4. Backend Changes

### 4.1 Delete

| Target | Reason |
|---|---|
| `ThreadMessage` class in `app/models/thread.py` | Redundant projection of ExecutionEvent |
| `thread_messages` table (Alembic migration) | Data is derivable from `execution_events` |
| `MessageProjectionSubscriber` in `app/core/events/subscribers/message_projection.py` | Maintains the deleted projection |
| `MessageProjectionSubscriber` registration in `app/main.py` | Dead reference |
| `GET /v1/threads/{thread_id}/messages` handler | Returns deleted model |
| `MessageResponse`, `CreateMessageRequest`, `ThreadDetailResponse` in `app/schemas/thread.py` | Schemas for deleted model (`ThreadDetailResponse` embeds `MessageResponse`) |
| `list_messages` in `app/services/thread_service.py` | Service method for deleted model |
| Frontend: `ThreadMessage` interface in `types/thread.ts` | Frontend type for deleted model |

### 4.2 Modify: `POST /v1/threads/{thread_id}/chat`

Extend `ChatRequest` to support file attachments:

```python
class ChatAttachment(BaseModel):
    filename: str
    storage_ref: str      # sandbox path from /v1/files/upload response
    mime_type: str
    size_bytes: int

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    # Raised from 4000 to 10000: debug scenarios include pasted logs, stack traces, config blocks
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=10)
```

Attachment payload is written into the `USER_MESSAGE` event **in the router** (`app/api/v1/threads.py`, chat endpoint, lines 185-195 — where `ExecutionEventEnvelope` is constructed), NOT in `dispatch_chat` (which only creates AgentRun + Execution):

```python
# In threads.py chat endpoint (after dispatch_chat returns):
payload = {"text": request.message}
if request.attachments:
    payload["attachments"] = [a.model_dump() for a in request.attachments]

user_msg_envelope = ExecutionEventEnvelope(
    execution_id=run.current_execution_id,
    run_id=run.id,
    workspace_id=workspace_id,
    event_type=ExecutionEventType.USER_MESSAGE,
    payload=payload,
    ...
)
await execution_event_bus.publish(user_msg_envelope, db)
```

`ChatResponse` unchanged:
```python
class ChatResponse(BaseModel):
    run_id: uuid.UUID
    execution_id: uuid.UUID
```

### 4.2.1 Also delete: `ThreadDetailResponse`

`ThreadDetailResponse` in `app/schemas/thread.py` embeds `messages: List[MessageResponse]`. Since `MessageResponse` is deleted, `ThreadDetailResponse` must also be deleted (or refactored to remove the `messages` field). The `/threads/{thread_id}` endpoint should return `ThreadResponse` instead.

### 4.3 New: `GET /v1/threads/{thread_id}/events`

Aggregates execution events across all runs in a thread. This is the chat history endpoint.

```sql
SELECT ee.id, ee.execution_id, ee.sequence_no, ee.event_type, ee.payload, ee.created_at,
       e.status as execution_status,
       ar.id as run_id
FROM execution_events ee
JOIN executions e ON ee.execution_id = e.id
JOIN agent_runs ar ON e.run_id = ar.id
WHERE ar.thread_id = :thread_id
ORDER BY ar.created_at, e.attempt_index, ee.sequence_no
```

Response:

```python
class ThreadEventResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    execution_id: uuid.UUID
    sequence_no: int
    event_type: str               # assistant_text, user_message, tool_use_start, etc.
    payload: dict
    execution_status: str
    created_at: datetime

class ThreadEventsListResponse(BaseModel):
    events: list[ThreadEventResponse]
    total: int
```

Supports cursor-based pagination via `?after=<event_id>&limit=100`. Using `event_id` (UUID) as cursor since `sequence_no` resets per execution and is not globally unique across the thread's event set. Server-side filtering: `copilot_*` events are excluded from the response (internal to copilot domain, not rendered in chat).

**Authorization:** Same workspace access check as existing thread endpoints — `require_workspace_role(viewer)` with `workspace_id` query param.

### 4.4 File Preview

Uploaded files: existing `GET /v1/files/read/{filename}` currently returns JSON-wrapped text (`BaseResponse` with `{filename, content, is_binary}`). For inline preview of images/PDFs, add a `?mode=raw` query param that returns raw binary bytes with correct `Content-Type` header via `Response(content=bytes, media_type=mime)`. This is a new code path in the existing endpoint, not a new endpoint.

Execution artifacts: already served by existing `GET /v1/artifacts/{thread_id}/{run_id}/download/{file_path}` which returns `FileResponse` with correct Content-Type. No new endpoint needed.

No new tables, no new models.

## 5. Frontend Architecture

### 5.1 Core Insight

ChatPanel and Graph Builder's ExecutionTimeline are **two views of the same data**. Both consume execution events; they differ only in rendering:

| | ExecutionTimeline | ChatPanel |
|---|---|---|
| Data source | Single execution's events | Thread's aggregated events |
| Rendering | Step cards + status indicators | Conversation bubbles + file preview |
| Streaming | WS subscription per execution | Same |
| History | `GET /v1/executions/{id}/events` | `GET /v1/threads/{id}/events` |

### 5.2 Component Structure: `frontend/components/chat/`

```
frontend/components/chat/
├── ChatPanel.tsx           — top-level orchestrator (reusable)
├── ChatHistory.tsx         — renders event list as conversation
├── ChatEventBubble.tsx     — single event → bubble (maps event_type to visual)
├── ChatInput.tsx           — textarea + file drop zone + attachment chips
├── ChatFilePreview.tsx     — inline preview by MIME type
├── AttachmentChip.tsx      — thumbnail chip for pending files
└── ThreadSidebar.tsx       — thread list + create/archive
```

### 5.3 ChatPanel Props

```tsx
interface ChatPanelProps {
  agentId: string
  workspaceId: string
  threadId?: string
  onThreadChange?: (id: string) => void
  showThreadSidebar?: boolean    // default true
  className?: string
}
```

Embedding (replaces `AgentChatTab`):
```tsx
<ChatPanel
  agentId={agentId}
  workspaceId={workspaceId}
  threadId={threadId}
  onThreadChange={(id) => router.push(`/agents/${agentId}?tab=chat&thread=${id}`)}
/>
```

### 5.4 Hooks

```
frontend/hooks/
├── use-thread-events.ts     — React Query: GET /v1/threads/{id}/events
├── use-chat-send.ts         — mutation: upload files + POST chat + track execution
└── use-chat-stream.ts       — wraps useExecutionStream, appends live events to cache
```

`useChatStream` flow:
1. `useChatSend` returns `{ execution_id }` after sending
2. `useChatStream` subscribes to WS for that `execution_id`
3. Live events appended to React Query cache for `thread-events`
4. On `execution_completed`, invalidate cache to get final persisted state

### 5.5 Event → Bubble Mapping

ChatEventBubble renders based on `event_type`:

| event_type | Visual |
|---|---|
| `user_message` | Right-aligned user bubble. `payload.text` as content. If `payload.attachments`, render file chips below. |
| `assistant_text` | Left-aligned assistant bubble. ReactMarkdown rendering. |
| `thinking` | Collapsible "Thinking..." block (muted style) |
| `tool_use_start` | Collapsible tool card: tool name + args |
| `tool_use_end` | Updates tool card: adds result, success/error indicator |
| `error` | Red-tinted error block with optional stack trace toggle |
| `artifact_created` | Artifact card with FilePreview (resolve via Artifact.uri) |
| `execution_started` | Subtle status indicator (not a bubble) |
| `execution_completed` | Status indicator: succeeded/failed/cancelled |
| `execution_status_change` | Ignored (internal lifecycle) |
| `copilot_*` | Not rendered in chat (separate domain) |

### 5.6 ChatInput

```
┌─────────────────────────────────────────────┐
│ [data.csv ×] [config.yaml ×]               │  ← attachment chips (removable)
├─────────────────────────────────────────────┤
│                                             │
│  Type your message...                       │  ← auto-expanding textarea
│                                             │
├─────────────────────────────────────────────┤
│ [Attach]                          [Send]    │  ← action bar
└─────────────────────────────────────────────┘

- Entire area is a file drop target
- Enter sends, Shift+Enter newline
- Files uploaded immediately via /v1/files/upload, chips show upload progress
- On send: POST /v1/threads/{id}/chat with message + attachment metadata
```

### 5.7 ChatFilePreview

| MIME category | Preview |
|---|---|
| `image/*` | `<img>` with max-height, click to fullscreen |
| `text/*`, `application/json`, source code | Syntax-highlighted block, max 50 lines + expand |
| `application/pdf` | Embedded viewer or PDF.js |
| Other | Download link with file icon + size |

## 6. Deletion Scope (Frontend)

| File | Replacement |
|---|---|
| `components/agents/agent-chat-tab.tsx` | `ChatPanel` |
| `components/threads/conversation-view.tsx` | `ChatHistory` + `ChatEventBubble` |
| `components/threads/thread-list.tsx` | `ThreadSidebar` |
| `hooks/use-agent-chat.ts` | `use-chat-send` + `use-chat-stream` |
| `hooks/queries/threads.ts` → `useChatMessage` | Removed (no message model) |
| `types/thread.ts` → `ThreadMessage` | Removed |
| `services/threadService.ts` → message methods | Removed |

Thread-related queries (`useThreads`, `useThread`, `useCreateThread`) stay — Thread model is unchanged.

## 7. What Stays Unchanged

- `Thread` model and table
- `AgentRun` model and table (already has `thread_id`)
- `Execution` model and table
- `ExecutionEvent` model and table
- `Artifact` model and table
- `POST /v1/files/upload` endpoint
- WS `/ws/executions` subscription
- `useExecutionStream` hook (wrapped by `useChatStream`)

## 8. Out of Scope

- SSE token-level streaming (WS execution events suffice)
- Cross-agent conversations (threads stay per-agent)
- End-user chat UI polish (developer debug tool)
- File editing (preview only)
- New database tables
