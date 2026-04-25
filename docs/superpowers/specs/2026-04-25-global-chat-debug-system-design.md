# Global Chat — Developer Debug Chat System Design

> Date: 2026-04-25
> Status: Draft
> Scope: Full-stack (backend model + API + frontend component system)

## 1. Problem Statement

The current `AgentChatTab` is a tightly-coupled page component with structural issues:

1. **Hardcoded context** — binds to `agentId`, router navigation, workspace resolution; impossible to reuse
2. **No file capability** — `ChatRequest` accepts plain text only; `ThreadMessage` has no attachment concept
3. **Primitive input** — single-line `<Input>`, no file upload, no attachment preview
4. **Dead storage model** — `ThreadMessage` is a flat JSONB blob (`content: Dict[str, Any]`) with no schema enforcement, no attachment support, and a leaky abstraction between "user typed text" and "execution produced output"
5. **No file preview** — neither uploaded files nor execution artifacts are previewable inline

## 2. Design Decisions (Confirmed)

| Decision | Choice | Rationale |
|---|---|---|
| Core positioning | Developer debug tool | Not end-user chat; focuses on testing agents, inspecting execution, uploading test files |
| Embedding model | Replace existing `AgentChatTab` | Reusable component injected via props, not route-coupled |
| Architecture | Independent domain layer (方案 B) | Clean separation: `chat` domain parallel to `agent`/`execution` domains |
| Message storage | Delete `ThreadMessage`, rebuild | Current model is unstructured JSONB blob; new model needs typed content blocks + native attachments |
| File model | New `MessageAttachment` table | FK to message + file storage; two-step flow (upload → reference) |
| Streaming | Reuse WS execution event stream | No new SSE; existing `/ws/executions` subscription is sufficient |
| File preview | Upload + artifact both supported | Inline preview by MIME type in conversation view |
| History | Reuse `Thread` model, per-Agent | Thread stays as-is; messages are rebuilt |

## 3. Backend: Data Model

### 3.1 Delete: `ThreadMessage` (table: `thread_messages`)

Remove the existing model, migration, service methods, and API endpoints that depend on it.

### 3.2 New: `ConversationMessage` (table: `conversation_messages`)

Replaces `ThreadMessage` with structured content. Named `ConversationMessage` (not `ChatMessage`) to avoid collision with the existing `ChatMessage` Pydantic schema in `openclaw_chat.py` and `code_agent/memory.py`.

```
conversation_messages
├── id              UUID PK
├── thread_id       UUID FK → threads (CASCADE)
├── execution_id    UUID FK → executions (SET NULL), nullable
├── role            VARCHAR(20) — "user" | "assistant" | "system" | "tool"
├── content_type    VARCHAR(20) — "text" | "markdown" | "code" | "error" | "tool_call" | "tool_result"
├── content_text    TEXT, nullable — the actual text/markdown/code content
├── content_meta    JSONB, nullable — structured metadata per content_type
│                   e.g. code: {language: "python"}, tool_call: {tool_name, args}, error: {code, trace}
├── seq             INTEGER — monotonically increasing per thread, for ordering
├── updated_at      TIMESTAMPTZ — for future edit/retry scenarios
├── created_at      TIMESTAMPTZ
```

**`seq` generation strategy:** Use `SELECT COALESCE(MAX(seq), 0) + 1 FROM conversation_messages WHERE thread_id = :tid FOR UPDATE` within the same transaction that creates the message. The `FOR UPDATE` lock on the thread's message rows prevents concurrent inserts from generating duplicate seq values. This is safe because:
- User messages are created synchronously in `dispatch_chat` (one at a time per thread)
- Assistant messages are created by `MessageProjectionSubscriber` only after execution completes (no concurrent assistant writes to the same thread)

Key changes from `ThreadMessage`:
- **`content` JSONB blob → `content_type` + `content_text` + `content_meta`**: typed, queryable, no more guessing what's inside
- **`run_id` removed**: `execution_id` is sufficient; `run_id` is a layer above that can be derived
- **`seq` added**: explicit ordering with transactional uniqueness guarantee
- **`updated_at` added**: supports future edit/retry without migration

### 3.3 New: `MessageAttachment` (table: `message_attachments`)

```
message_attachments
├── id              UUID PK
├── message_id      UUID FK → conversation_messages (CASCADE)
├── file_name       VARCHAR(255)
├── mime_type       VARCHAR(100)
├── size_bytes      BIGINT
├── storage_ref     VARCHAR(500) — path in sandbox/object-store
├── source          VARCHAR(20) — "upload" | "artifact"
│                   upload: user-attached file
│                   artifact: execution-produced file
├── metadata        JSONB, nullable — dimensions for images, language for code, page count for PDF
├── created_at      TIMESTAMPTZ
```

Note: `preview_ready` removed — preview is computed on-the-fly by MIME type at the endpoint level, no async pipeline needed.

### 3.4 New: `StagedUpload` (table: `staged_uploads`)

The existing `POST /v1/files/upload` writes files to the Docker sandbox and returns `{filename, path, size}` — no UUID, no database record. Chat attachments need a UUID reference that can be linked to a message. `StagedUpload` is a short-lived staging table for this purpose.

```
staged_uploads
├── id              UUID PK — this is the "attachment_id" referenced by ChatRequest
├── user_id         VARCHAR(255) FK → user (CASCADE)
├── workspace_id    UUID FK → workspaces
├── file_name       VARCHAR(255)
├── mime_type       VARCHAR(100)
├── size_bytes      BIGINT
├── storage_ref     VARCHAR(500) — sandbox path (e.g. /workspace/uploads/data.csv)
├── status          VARCHAR(20) — "staged" | "attached" | "expired"
├── expires_at      TIMESTAMPTZ — auto-expire unattached uploads after 1 hour
├── created_at      TIMESTAMPTZ
```

**Flow:**
1. `POST /v1/chat/upload` (new endpoint) → validates file, writes to sandbox, creates `StagedUpload` row → returns `{ id: UUID, file_name, mime_type, size_bytes }`
2. `POST /v1/threads/{thread_id}/chat` with `attachment_ids: [uuid]` → resolves `StagedUpload` rows, creates `MessageAttachment` records, marks staged uploads as `attached`
3. A periodic cleanup job expires `staged` uploads older than 1 hour

This is a **separate endpoint from `/v1/files/upload`** — the existing file upload serves sandbox file management; the new one serves chat attachment staging. No patching of the existing endpoint.

### 3.5 Thread Model (unchanged)

`Thread` stays as-is. It remains the grouping entity: `Thread` belongs to `Agent` + `Workspace`, `ConversationMessage` belongs to `Thread`.

## 4. Backend: API Changes

### 4.1 Modified Endpoints

**`POST /v1/threads/{thread_id}/chat`** — send a message with optional attachments

```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    # Raised from 4000 to 10000: debug scenarios often include pasted logs, stack traces, config blocks
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # attachment_ids reference StagedUpload rows from POST /v1/chat/upload
```

Response:
```python
class ChatResponse(BaseModel):
    message_id: uuid.UUID    # the created ConversationMessage id
    run_id: uuid.UUID
    execution_id: uuid.UUID
```

Note: this `ChatResponse` is in `app/schemas/thread.py`. It is distinct from `app/schemas/chat.py`'s `ChatResponse` (which serves the OpenClaw chat endpoint with `thread_id`, `response`, `duration_ms`).

**`GET /v1/threads/{thread_id}/messages`** — returns `ConversationMessage` + nested `attachments`

```python
class AttachmentResponse(BaseModel):
    id: uuid.UUID
    file_name: str
    mime_type: str
    size_bytes: int
    source: Literal["upload", "artifact"]
    preview_url: str          # computed: /v1/files/preview/{id}

class ConversationMessageResponse(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    execution_id: uuid.UUID | None
    role: str
    content_type: str
    content_text: str | None
    content_meta: dict | None
    seq: int
    attachments: list[AttachmentResponse]
    created_at: datetime
```

### 4.2 New Endpoints

**`POST /v1/chat/upload`** — stage a file for chat attachment

Accepts multipart file upload. Validates (same rules as `/v1/files/upload`), writes to sandbox, creates `StagedUpload` row. Returns `{ id, file_name, mime_type, size_bytes }`.

**`GET /v1/files/preview/{attachment_id}`** — file preview endpoint

Looks up `MessageAttachment` by id, reads file from `storage_ref`:
- Images (png/jpg/gif/webp/svg): return binary with correct Content-Type
- Code/text files: return `{ content: str, language: str }`
- PDF: return binary stream
- Other: return download URL

### 4.3 Orchestrator Changes

`ExecutionOrchestrator.dispatch_chat()` signature updated:

```python
async def dispatch_chat(
    self,
    thread_id: UUID,
    message: str,
    user_id: str,
    attachment_ids: list[UUID] | None = None,  # NEW
) -> ChatDispatchResult:
```

Updated flow:
1. Acquire next `seq` via `SELECT MAX(seq)+1 ... FOR UPDATE` within transaction
2. Create `ConversationMessage` (role=user, content_type=text, seq=seq)
3. If `attachment_ids`: resolve `StagedUpload` rows, create `MessageAttachment` records, mark staged uploads as `attached`
4. Create `AgentRun` + `Execution` (unchanged)
5. Return `ChatDispatchResult(message_id, run_id, execution_id)`

### 4.4 MessageProjectionSubscriber Rewrite

The subscriber is rewritten to create `ConversationMessage` records instead of `ThreadMessage`. Event type → message mapping:

| ExecutionEventType | → role | → content_type | → content_text | → content_meta |
|---|---|---|---|---|
| `USER_MESSAGE` | user | text | `payload["text"]` | `None` |
| `ASSISTANT_TEXT` | assistant | markdown | `payload["text"]` | `None` |
| `THINKING` | assistant | text | `payload["text"]` | `{"thinking": true}` |
| `TOOL_USE_START` | tool | tool_call | `json.dumps(payload["input"])` | `{"tool_name": payload["name"]}` |
| `TOOL_USE_END` | tool | tool_result | `payload.get("output", "")` | `{"tool_name": payload["name"], "success": payload.get("success", true)}` |
| `ERROR` | system | error | `payload["message"]` | `{"code": payload.get("code"), "trace": payload.get("trace")}` |
| `ARTIFACT_CREATED` | assistant | text | `f"Artifact created: {payload['name']}"` | `{"artifact_id": payload["id"]}` — also creates `MessageAttachment(source="artifact")` |
| `EXECUTION_COMPLETED` (succeeded) | assistant | markdown | `envelope.result_summary` | `None` |
| `EXECUTION_COMPLETED` (failed/cancelled) | system | error | `f"Execution {status}: {error}"` | `None` |

Events NOT projected (lifecycle-only, no user-visible content):
- `EXECUTION_STARTED`, `EXECUTION_STATUS_CHANGE` — status tracking, not messages
- `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED` — handled by execution UI, not chat
- `COPILOT_*` events — separate copilot domain, not projected into thread chat

## 5. Frontend: Architecture

### 5.1 Domain Layer: `/frontend/domains/chat/`

New top-level domain, parallel to existing concerns:

```
frontend/domains/chat/
├── types.ts              — ConversationMessage, Attachment, ChatThread interfaces
├── services/
│   └── chatService.ts    — API calls (listMessages, sendChat, stageUpload, getPreview)
├── hooks/
│   ├── useChatMessages.ts    — React Query hook for messages
│   ├── useChatSend.ts        — mutation: upload files → send message → track execution
│   └── useChatStream.ts      — WS subscription for active execution, inserts streaming messages
├── stores/
│   └── chatPanelStore.ts     — Zustand: activeThreadId, activeAgentId, inputDraft, pendingFiles
├── components/
│   ├── ChatPanel.tsx         — top-level orchestrator (the reusable component)
│   ├── ThreadSidebar.tsx     — thread list + create/archive
│   ├── MessageList.tsx       — scrollable message stream
│   ├── MessageBubble.tsx     — single message: renders content_type + attachments
│   ├── ChatInput.tsx         — rich input: textarea + file drop zone + attachment chips
│   ├── FilePreview.tsx       — inline preview by MIME type
│   ├── AttachmentChip.tsx    — thumbnail chip for attached files (pre-send)
│   └── AgentSelector.tsx     — agent picker dropdown (for standalone use)
```

### 5.2 ChatPanel — The Reusable Component

```tsx
interface ChatPanelProps {
  agentId: string
  workspaceId: string
  threadId?: string              // optional: pre-select a thread
  onThreadChange?: (id: string) => void  // callback for URL sync
  showThreadSidebar?: boolean    // default true
  showAgentSelector?: boolean    // default false (agent already known when embedded)
  className?: string
}

export function ChatPanel({ agentId, workspaceId, ... }: ChatPanelProps) {
  // ... orchestrates child components
}
```

**Embedding in AgentChatTab** (replacement):
```tsx
// In agent detail page — replaces the entire AgentChatTab component
<ChatPanel
  agentId={agentId}
  workspaceId={workspaceId}
  threadId={threadId}
  onThreadChange={(id) => router.push(`/agents/${agentId}?tab=chat&thread=${id}`)}
/>
```

### 5.3 ChatInput — Rich Input Area

```
┌─────────────────────────────────────────────┐
│ [attachment1.py ×] [data.csv ×]             │  ← attachment chips (removable)
├─────────────────────────────────────────────┤
│                                             │
│  Type your message...                       │  ← auto-expanding textarea
│                                             │
├─────────────────────────────────────────────┤
│ [📎 Attach]                      [Send ▶]  │  ← action bar
└─────────────────────────────────────────────┘

Drop zone: entire input area is a drop target for files
Keyboard: Enter sends, Shift+Enter newline
```

### 5.4 MessageBubble — Content Type Rendering

Based on `content_type`:

| content_type | Rendering |
|---|---|
| `text` | Plain text, whitespace-preserved |
| `markdown` | ReactMarkdown with syntax highlighting |
| `code` | CodeMirror read-only block with language hint from `content_meta` |
| `error` | Red-tinted block with error icon, optional stack trace toggle |
| `tool_call` | Collapsible: tool name + JSON args |
| `tool_result` | Collapsible: tool name + result |

Attachments are rendered below the text content as `FilePreview` components.

### 5.5 FilePreview — Inline Preview

| MIME category | Preview |
|---|---|
| `image/*` | `<img>` with max-height, click to fullscreen |
| `text/*`, `application/json`, source code | Syntax-highlighted code block (read-only CodeMirror), max 100 lines with "expand" |
| `application/pdf` | Embedded `<iframe>` or PDF.js viewer |
| Other | Download link with file icon + size |

### 5.6 Streaming Integration

`useChatStream` hook wraps the existing `useExecutionStream`:

1. User sends message → `useChatSend` returns `{ message_id, execution_id }`
2. `useChatStream` subscribes to `/ws/executions` for that `execution_id`
3. As `event` frames arrive, they are projected into temporary `ChatMessage` objects and appended to the React Query cache
4. On `execution_completed`, the hook invalidates the messages query to replace temporary messages with the final persisted ones

## 6. Deletion Scope

### Backend (delete)
- `app/models/thread.py` → remove `ThreadMessage` class
- `app/schemas/thread.py` → remove `MessageResponse`, `CreateMessageRequest`
- `app/services/thread_service.py` → remove `list_messages`, rewrite chat flow
- Migration: drop `thread_messages` table

### Frontend (delete)
- `components/agents/agent-chat-tab.tsx` — replaced by `ChatPanel`
- `components/threads/conversation-view.tsx` — replaced by `MessageList` + `MessageBubble`
- `components/threads/thread-list.tsx` — replaced by `ThreadSidebar`
- `hooks/use-agent-chat.ts` — replaced by `useChatSend` + `useChatStream`
- `hooks/queries/threads.ts` → `useChatMessage` mutation removed, thread queries stay
- `types/thread.ts` → `ThreadMessage` interface removed
- `services/threadService.ts` → chat/message methods removed

## 7. Migration Strategy

1. Create new tables (`conversation_messages`, `message_attachments`, `staged_uploads`) via Alembic migration
2. Migrate existing `thread_messages` data → `conversation_messages` (content JSONB → content_type + content_text, seq backfilled from row_number ordered by created_at)
3. Drop `thread_messages` table
4. Build frontend `domains/chat/` from scratch
5. Replace `AgentChatTab` with `ChatPanel`
6. Delete old components/hooks/services

## 8. Out of Scope

- SSE token-level streaming (use WS execution events)
- Cross-agent conversations (threads stay per-agent)
- End-user facing chat UI polish (this is a dev debug tool)
- File editing capabilities (preview only)
- Real-time collaborative chat (single-user debugging)
