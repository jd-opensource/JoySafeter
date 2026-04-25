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

### 3.2 New: `ChatMessage` (table: `chat_messages`)

Replaces `ThreadMessage` with structured content.

```
chat_messages
├── id              UUID PK
├── thread_id       UUID FK → threads (CASCADE)
├── execution_id    UUID FK → executions (SET NULL), nullable
├── role            VARCHAR(20) — "user" | "assistant" | "system" | "tool"
├── content_type    VARCHAR(20) — "text" | "markdown" | "code" | "error" | "tool_call" | "tool_result"
├── content_text    TEXT, nullable — the actual text/markdown/code content
├── content_meta    JSONB, nullable — structured metadata per content_type
│                   e.g. code: {language: "python"}, tool_call: {tool_name, args}, error: {code, trace}
├── seq             INTEGER — monotonically increasing per thread, for ordering
├── created_at      TIMESTAMPTZ
```

Key changes from `ThreadMessage`:
- **`content` JSONB blob → `content_type` + `content_text` + `content_meta`**: typed, queryable, no more guessing what's inside
- **`run_id` removed**: `execution_id` is sufficient; `run_id` is a layer above that can be derived
- **`seq` added**: explicit ordering instead of relying on `created_at` ties

### 3.3 New: `MessageAttachment` (table: `message_attachments`)

```
message_attachments
├── id              UUID PK
├── message_id      UUID FK → chat_messages (CASCADE)
├── file_name       VARCHAR(255)
├── mime_type       VARCHAR(100)
├── size_bytes      BIGINT
├── storage_ref     VARCHAR(500) — path in sandbox/object-store
├── source          VARCHAR(20) — "upload" | "artifact"
│                   upload: user-attached file
│                   artifact: execution-produced file
├── preview_ready   BOOLEAN DEFAULT false — whether preview has been generated
├── metadata        JSONB, nullable — dimensions for images, language for code, page count for PDF
├── created_at      TIMESTAMPTZ
```

### 3.4 Thread Model (unchanged)

`Thread` stays as-is. It remains the grouping entity: `Thread` belongs to `Agent` + `Workspace`, `ChatMessage` belongs to `Thread`.

## 4. Backend: API Changes

### 4.1 Modified Endpoints

**`POST /v1/threads/{thread_id}/chat`** — send a message with optional attachments

```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # attachment_ids reference files previously uploaded via POST /v1/files/upload
```

Response (unchanged shape):
```python
class ChatResponse(BaseModel):
    message_id: uuid.UUID    # NEW: the created ChatMessage id
    run_id: uuid.UUID
    execution_id: uuid.UUID
```

**`GET /v1/threads/{thread_id}/messages`** — returns `ChatMessage` + nested `attachments`

```python
class AttachmentResponse(BaseModel):
    id: uuid.UUID
    file_name: str
    mime_type: str
    size_bytes: int
    source: Literal["upload", "artifact"]
    preview_url: str          # computed: /v1/files/preview/{id}

class ChatMessageResponse(BaseModel):
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

**`GET /v1/files/preview/{attachment_id}`** — file preview endpoint

- Images (png/jpg/gif/webp/svg): return binary with correct Content-Type
- Code/text files: return `{ content: str, language: str }`
- PDF: return binary stream
- Other: return download URL

### 4.3 Orchestrator Changes

`ExecutionOrchestrator.dispatch_chat()` updated to:
1. Create `ChatMessage` (role=user, content_type=text) with `seq`
2. Create `MessageAttachment` records for each `attachment_id` (link uploaded files to the message)
3. Create `AgentRun` + `Execution` (unchanged)
4. On execution completion, the `MessageProjectionSubscriber` creates assistant `ChatMessage` records from execution events

## 5. Frontend: Architecture

### 5.1 Domain Layer: `/frontend/domains/chat/`

New top-level domain, parallel to existing concerns:

```
frontend/domains/chat/
├── types.ts              — ChatMessage, Attachment, ChatThread interfaces
├── services/
│   └── chatService.ts    — API calls (listMessages, sendChat, uploadFile, getPreview)
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

1. Create new tables (`chat_messages`, `message_attachments`) via Alembic migration
2. Migrate existing `thread_messages` data → `chat_messages` (content JSONB → content_type + content_text)
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
