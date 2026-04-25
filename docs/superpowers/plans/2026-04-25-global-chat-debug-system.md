# Global Chat Debug System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the coupled `AgentChatTab` with a reusable `ChatPanel` that renders execution events as conversation, supports file upload/preview, and eliminates the redundant `ThreadMessage` projection layer.

**Architecture:** ExecutionEvent is the source of truth. Chat history = aggregated execution events across a thread's runs. The frontend ChatPanel is a view layer over execution events — same data source as Graph Builder's ExecutionTimeline, different rendering. Zero new database tables.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js 16 + React 19 + Zustand + React Query + Vitest (frontend)

**Spec:** `docs/superpowers/specs/2026-04-25-global-chat-debug-system-design.md`

---

## File Structure

### Backend — Modified

| File | Change |
|---|---|
| `backend/app/models/thread.py` | Remove `ThreadMessage` class |
| `backend/app/models/__init__.py` | Remove `ThreadMessage` import/export |
| `backend/app/schemas/thread.py` | Remove `MessageResponse`, `CreateMessageRequest`, `ThreadDetailResponse`; add `ChatAttachment`, `ThreadEventResponse`, `ThreadEventsListResponse`; extend `ChatRequest` |
| `backend/app/api/v1/threads.py` | Remove `list_messages` endpoint; modify `chat` endpoint for attachments; modify `get_thread` to return `ThreadResponse`; add `list_thread_events` endpoint |
| `backend/app/api/v1/files.py` | Add `?mode=raw` code path to `read_file` |
| `backend/app/services/thread_service.py` | Remove `list_messages`, `message_repo`; add `list_thread_events` |
| `backend/app/repositories/thread.py` | Remove `ThreadMessageRepository` |
| `backend/app/main.py:193,199` | Remove `MessageProjectionSubscriber` import and registration |

### Backend — Deleted

| File | Reason |
|---|---|
| `backend/app/core/events/subscribers/message_projection.py` | Redundant projection subscriber |

### Backend — Created

| File | Purpose |
|---|---|
| `backend/alembic/versions/YYYYMMDD_drop_thread_messages.py` | Migration to drop `thread_messages` table |
| `backend/tests/api/test_thread_events.py` | Tests for new events endpoint |

### Frontend — Created

| File | Purpose |
|---|---|
| `frontend/components/chat/ChatPanel.tsx` | Top-level reusable orchestrator |
| `frontend/components/chat/ChatHistory.tsx` | Renders event list as conversation |
| `frontend/components/chat/ChatEventBubble.tsx` | Single event → visual bubble |
| `frontend/components/chat/ChatInput.tsx` | Rich textarea + file drop zone + attachment chips |
| `frontend/components/chat/ChatFilePreview.tsx` | Inline file preview by MIME type |
| `frontend/components/chat/AttachmentChip.tsx` | Thumbnail chip for pending files |
| `frontend/components/chat/ThreadSidebar.tsx` | Thread list + create/archive |
| `frontend/hooks/use-thread-events.ts` | React Query hook for `GET /v1/threads/{id}/events` |
| `frontend/hooks/use-chat-send.ts` | Mutation: upload files + POST chat + track execution |
| `frontend/hooks/use-chat-stream.ts` | Wraps `useExecutionStream`, appends live events to cache |

### Frontend — Modified

| File | Change |
|---|---|
| `frontend/app/agents/[agentId]/page.tsx` | Replace `AgentChatTab` import with `ChatPanel` |
| `frontend/types/thread.ts` | Remove `ThreadMessage`, `ThreadDetail`; add `ThreadEvent` |
| `frontend/services/threadService.ts` | Remove `listMessages`, `chat`; add `listThreadEvents`, `sendChat` (with attachments) |
| `frontend/hooks/queries/threads.ts` | Remove `useThreadMessages`, `useChatMessage` |

### Frontend — Deleted

| File | Replacement |
|---|---|
| `frontend/components/agents/agent-chat-tab.tsx` | `ChatPanel` |
| `frontend/components/threads/conversation-view.tsx` | `ChatHistory` + `ChatEventBubble` |
| `frontend/components/threads/thread-list.tsx` | `ThreadSidebar` |
| `frontend/hooks/use-agent-chat.ts` | `use-chat-send` + `use-chat-stream` |

---

## Task 1: Backend — Delete ThreadMessage & MessageProjectionSubscriber

**Files:**
- Modify: `backend/app/models/thread.py` (remove `ThreadMessage` class, lines 44-72)
- Modify: `backend/app/models/__init__.py` (remove `ThreadMessage` import)
- Delete: `backend/app/core/events/subscribers/message_projection.py`
- Modify: `backend/app/main.py:193,199` (remove subscriber import + registration)
- Modify: `backend/app/repositories/thread.py` (remove `ThreadMessageRepository`)
- Modify: `backend/app/services/thread_service.py` (remove `message_repo`, `list_messages`, `get_thread_with_messages`)
- Create: `backend/alembic/versions/20260425_000001_drop_thread_messages.py`

- [ ] **Step 1: Remove `ThreadMessage` from model**

In `backend/app/models/thread.py`, delete the `ThreadMessage` class (lines 44-72) and remove the `messages` relationship from `Thread` class (lines 38-40). Remove the `ThreadMessage` import guard in `TYPE_CHECKING` if present.

- [ ] **Step 2: Remove ThreadMessage from `__init__.py`**

In `backend/app/models/__init__.py`, remove `ThreadMessage` from imports and `__all__`.

- [ ] **Step 3: Delete `message_projection.py`**

Delete `backend/app/core/events/subscribers/message_projection.py` entirely.

- [ ] **Step 4: Unregister subscriber in `main.py`**

In `backend/app/main.py`, remove line 193 (`from ... import MessageProjectionSubscriber`) and line 199 (`execution_event_bus.register(MessageProjectionSubscriber())`).

- [ ] **Step 5: Remove `ThreadMessageRepository`**

In `backend/app/repositories/thread.py`, remove the `ThreadMessageRepository` class. Keep `ThreadRepository`.

- [ ] **Step 6: Clean up `ThreadService`**

In `backend/app/services/thread_service.py`:
- Remove `ThreadMessage` import
- Remove `ThreadMessageRepository` import
- Remove `self.message_repo` from `__init__`
- Remove `list_messages` method (lines 97-102)
- Remove `get_thread_with_messages` method (lines 38-42)

**Important:** The `get_thread` router handler in `threads.py` currently calls `service.get_thread_with_messages()`. This will break until Task 2 Step 2 changes it to call `service.get_thread()`. Both steps are in the same commit scope (Tasks 1+2 can be committed together if needed), but be aware of this dependency.

- [ ] **Step 7: Create Alembic migration to drop `thread_messages` table**

```bash
cd backend && uv run alembic revision --autogenerate -m "drop thread_messages table"
```

Verify the generated migration contains `op.drop_table('thread_messages')`. Edit if needed.

- [ ] **Step 8: Verify backend compiles**

```bash
cd backend && python -c "from app.models.thread import Thread; print('OK')"
```

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "refactor: delete ThreadMessage model and MessageProjectionSubscriber

ThreadMessage was a redundant projection of ExecutionEvent.
MessageProjectionSubscriber maintained this projection.
Both removed — ExecutionEvent is the single source of truth."
```

---

## Task 2: Backend — Extend ChatRequest with Attachments

**Files:**
- Modify: `backend/app/schemas/thread.py` (add `ChatAttachment`, extend `ChatRequest`, remove dead schemas)
- Modify: `backend/app/api/v1/threads.py` (modify `chat` endpoint, modify `get_thread`, remove `list_messages`)

- [ ] **Step 1: Update schemas**

In `backend/app/schemas/thread.py`:

Remove `MessageResponse`, `CreateMessageRequest`, `ThreadDetailResponse`.

Add:
```python
class ChatAttachment(BaseModel):
    filename: str = Field(..., max_length=255)
    storage_ref: str = Field(..., max_length=500)
    mime_type: str = Field(..., max_length=100)
    size_bytes: int = Field(..., gt=0)
```

Extend `ChatRequest`:
```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=10)
```

- [ ] **Step 2: Update `threads.py` router — remove `list_messages`, fix `get_thread`**

In `backend/app/api/v1/threads.py`:

Remove the `list_messages` endpoint entirely (lines 118-132).

Remove `MessageResponse`, `ThreadDetailResponse` from the schema import.

Change `get_thread` to return `BaseResponse[ThreadResponse]` instead of `BaseResponse[ThreadDetailResponse]`:
```python
@router.get("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def get_thread(...) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    return BaseResponse(success=True, code=200, msg="ok", data=ThreadResponse.model_validate(thread))
```

- [ ] **Step 3: Update `chat` endpoint to include attachments in event payload**

In the `chat` endpoint in `threads.py`, modify the `USER_MESSAGE` envelope construction (lines 185-195):

```python
    payload = {"text": request.message}
    if request.attachments:
        payload["attachments"] = [a.model_dump() for a in request.attachments]

    user_msg_envelope = ExecutionEventEnvelope(
        execution_id=run.current_execution_id,
        run_id=run.id,
        workspace_id=workspace_id,
        event_type=ExecutionEventType.USER_MESSAGE,
        payload=payload,
        created_at=utc_now(),
        trigger_source="chat",
        thread_id=thread_id,
    )
```

- [ ] **Step 4: Verify backend starts**

```bash
cd backend && python -c "from app.api.v1.threads import router; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: extend ChatRequest with file attachments

Add ChatAttachment schema, extend ChatRequest to accept attachments list.
Attachment metadata is written into USER_MESSAGE event payload.
Remove dead schemas: MessageResponse, CreateMessageRequest, ThreadDetailResponse."
```

---

## Task 3: Backend — Add `GET /v1/threads/{thread_id}/events` Endpoint

**Files:**
- Modify: `backend/app/schemas/thread.py` (add `ThreadEventResponse`, `ThreadEventsListResponse`)
- Modify: `backend/app/services/thread_service.py` (add `list_thread_events`)
- Modify: `backend/app/api/v1/threads.py` (add `list_thread_events` endpoint)
- Create: `backend/tests/api/test_thread_events.py`

- [ ] **Step 1: Add response schemas**

In `backend/app/schemas/thread.py`, add:

```python
class ThreadEventResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    execution_id: uuid.UUID
    sequence_no: int
    event_type: str
    payload: Dict[str, Any]
    execution_status: str
    created_at: datetime

    model_config = {"from_attributes": True}

class ThreadEventsListResponse(BaseModel):
    events: list[ThreadEventResponse]
    total: int
```

- [ ] **Step 2: Add service method**

In `backend/app/services/thread_service.py`, add:

```python
from sqlalchemy import select, func, and_, not_
from app.models.execution import Execution, ExecutionEvent
from app.models.agent_run import AgentRun

class ThreadService:
    # ... existing methods ...

    async def list_thread_events(
        self,
        thread_id: uuid.UUID,
        after_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> tuple[list[dict], int]:
        """Aggregate execution events across all runs in a thread."""
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")

        base_filter = and_(
            AgentRun.thread_id == thread_id,
            not_(ExecutionEvent.event_type.like("copilot_%")),
        )

        count_q = (
            select(func.count(ExecutionEvent.id))
            .join(Execution, ExecutionEvent.execution_id == Execution.id)
            .join(AgentRun, Execution.run_id == AgentRun.id)
            .where(base_filter)
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        query = (
            select(
                ExecutionEvent.id,
                ExecutionEvent.execution_id,
                ExecutionEvent.sequence_no,
                ExecutionEvent.event_type,
                ExecutionEvent.payload,
                ExecutionEvent.created_at,
                Execution.status.label("execution_status"),
                AgentRun.id.label("run_id"),
            )
            .join(Execution, ExecutionEvent.execution_id == Execution.id)
            .join(AgentRun, Execution.run_id == AgentRun.id)
            .where(base_filter)
            .order_by(AgentRun.created_at, Execution.attempt_index, ExecutionEvent.sequence_no)
        )

        if after_id:
            ref_event = (await self.db.execute(
                select(ExecutionEvent.created_at).where(ExecutionEvent.id == after_id)
            )).scalar()
            if ref_event:
                query = query.where(ExecutionEvent.created_at > ref_event)

        query = query.limit(limit)
        rows = (await self.db.execute(query)).mappings().all()
        return [dict(r) for r in rows], total
```

- [ ] **Step 3: Add router endpoint**

In `backend/app/api/v1/threads.py`, add after the artifacts endpoint:

```python
from app.schemas.thread import ThreadEventResponse, ThreadEventsListResponse

@router.get("/{thread_id}/events", response_model=BaseResponse[ThreadEventsListResponse])
async def list_thread_events(
    thread_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    after: uuid.UUID | None = Query(None, description="Cursor: event ID to paginate after"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadEventsListResponse]:
    """List aggregated execution events across all runs in this thread."""
    service = ThreadService(db)
    events, total = await service.list_thread_events(thread_id, after_id=after, limit=limit)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=ThreadEventsListResponse(
            events=[ThreadEventResponse(**e) for e in events],
            total=total,
        ),
    )
```

- [ ] **Step 4: Write test**

Create `backend/tests/api/test_thread_events.py`:

```python
"""Tests for GET /v1/threads/{thread_id}/events endpoint."""
import pytest


class TestListThreadEvents:
    """Test the thread events aggregation endpoint."""

    async def test_returns_empty_for_new_thread(self, client, auth_headers, thread_factory):
        thread = await thread_factory()
        resp = await client.get(
            f"/api/v1/threads/{thread.id}/events?workspace_id={thread.workspace_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["events"] == []
        assert data["total"] == 0

    async def test_excludes_copilot_events(self, client, auth_headers, thread_with_events):
        thread, _ = thread_with_events
        resp = await client.get(
            f"/api/v1/threads/{thread.id}/events?workspace_id={thread.workspace_id}",
            headers=auth_headers,
        )
        data = resp.json()["data"]
        event_types = [e["event_type"] for e in data["events"]]
        assert not any(t.startswith("copilot_") for t in event_types)

    async def test_pagination_with_after_cursor(self, client, auth_headers, thread_with_events):
        thread, _ = thread_with_events
        resp1 = await client.get(
            f"/api/v1/threads/{thread.id}/events?workspace_id={thread.workspace_id}&limit=1",
            headers=auth_headers,
        )
        events1 = resp1.json()["data"]["events"]
        if len(events1) > 0:
            cursor = events1[-1]["id"]
            resp2 = await client.get(
                f"/api/v1/threads/{thread.id}/events?workspace_id={thread.workspace_id}&after={cursor}",
                headers=auth_headers,
            )
            assert resp2.status_code == 200
```

- [ ] **Step 5: Run test**

```bash
cd backend && uv run pytest tests/api/test_thread_events.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: add GET /v1/threads/{thread_id}/events endpoint

Aggregates execution events across all runs in a thread.
Cursor-based pagination via ?after=<event_id>.
Filters out copilot_* events server-side."
```

---

## Task 4: Backend — File Preview Raw Mode

**Files:**
- Modify: `backend/app/api/v1/files.py` (add `?mode=raw` to `read_file`)

- [ ] **Step 1: Add raw mode to `read_file` endpoint**

In `backend/app/api/v1/files.py`, modify the `read_file` function to support `?mode=raw`:

```python
import mimetypes as mimetypes_module
from fastapi.responses import Response

@router.get(
    "/read/{filename}",
    summary="Read file content",
    description="Read the content of a file. Use ?mode=raw for binary content with correct Content-Type.",
    responses={
        200: {"description": "File content"},
        404: {"description": "File not found"},
        500: {"description": "Failed to read file"},
    },
)
async def read_file(
    request: Request,
    filename: str,
    current_user: CurrentUser,
    mode: str = Query("json", description="Response mode: 'json' (default) or 'raw' (binary with Content-Type)"),
) -> BaseResponse[dict] | Response:
    client_ip = get_client_ip(request)

    try:
        safe_filename = sanitize_filename(filename)
        container_path = get_container_path(safe_filename)

        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            if mode == "raw":
                content_bytes = await asyncio.to_thread(
                    handle.adapter.raw_read_bytes, container_path
                )
                if content_bytes is None:
                    raise NotFoundException("File not found")
                mime, _ = mimetypes_module.guess_type(safe_filename)
                return Response(
                    content=content_bytes,
                    media_type=mime or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
                )

            content = await asyncio.to_thread(handle.adapter.raw_read, container_path)

        if content.startswith("[Error:") or content.startswith("Error:"):
            raise NotFoundException("File not found")

        is_binary = False
        try:
            content.encode("utf-8")
        except UnicodeEncodeError:
            content = base64.b64encode(content.encode("latin-1")).decode("ascii")
            is_binary = True

        logger.info(f"File read: user={current_user.id}, filename={safe_filename}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="Read file successfully",
            data={"filename": safe_filename, "content": content, "is_binary": is_binary},
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to read file: error={e}", exc_info=True)
        raise InternalServerException("Failed to read file") from e
```

Note: `raw_read_bytes` may not exist on the adapter. If only `raw_read` (text) is available, use `adapter.raw_read(path)` then encode: `content.encode('latin-1')` for binary, and determine MIME from filename. Check `live_read_file` in `artifacts.py` for the adapter read pattern used there.

Artifact content preview is already handled by `GET /v1/artifacts/{thread_id}/{run_id}/download/{file_path}` — no additional work needed.

- [ ] **Step 2: Verify endpoint works**

```bash
cd backend && python -c "from app.api.v1.files import router; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: add raw mode to file read endpoint for binary preview

GET /v1/files/read/{filename}?mode=raw returns binary bytes with
correct Content-Type header, enabling inline image/PDF preview."
```

---

## Task 5: Frontend — Types, Service, Hooks

**Files:**
- Modify: `frontend/types/thread.ts` (remove `ThreadMessage`, `ThreadDetail`; add `ThreadEvent`)
- Modify: `frontend/services/threadService.ts` (remove message methods; add `listThreadEvents`, `sendChat`)
- Modify: `frontend/hooks/queries/threads.ts` (remove `useThreadMessages`, `useChatMessage`)
- Create: `frontend/hooks/use-thread-events.ts`
- Create: `frontend/hooks/use-chat-send.ts`
- Create: `frontend/hooks/use-chat-stream.ts`

- [ ] **Step 1: Update `types/thread.ts`**

Remove `ThreadMessage` interface (lines 12-20) and `ThreadDetail` interface (lines 22-24). Add:

```ts
export interface ChatAttachment {
  filename: string
  storage_ref: string
  mime_type: string
  size_bytes: number
}

export interface ThreadEvent {
  id: string
  run_id: string
  execution_id: string
  sequence_no: number
  event_type: string
  payload: Record<string, unknown>
  execution_status: string
  created_at: string
}
```

- [ ] **Step 2: Update `services/threadService.ts`**

Remove `listMessages` and `chat` methods. Add:

```ts
import type { ChatAttachment, ThreadEvent } from '@/types/thread'

listThreadEvents: async (
  threadId: string,
  workspaceId: string,
  options?: { after?: string; limit?: number },
): Promise<{ events: ThreadEvent[]; total: number }> => {
  const params = new URLSearchParams({ workspace_id: workspaceId })
  if (options?.after) params.set('after', options.after)
  if (options?.limit) params.set('limit', String(options.limit))
  return apiGet(`threads/${threadId}/events?${params}`)
},

sendChat: async (
  threadId: string,
  workspaceId: string,
  message: string,
  attachments: ChatAttachment[] = [],
): Promise<{ run_id: string; execution_id: string }> => {
  return apiPost(`threads/${threadId}/chat?workspace_id=${workspaceId}`, {
    message,
    attachments,
  })
},
```

- [ ] **Step 3: Update `hooks/queries/threads.ts`**

Remove `useThreadMessages` and `useChatMessage`. Keep `useThreads`, `useThread`, `useCreateThread`, `useUpdateThread`, `useArchiveThread`. Remove `threadKeys.messages`.

- [ ] **Step 4: Create `hooks/use-thread-events.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { threadService } from '@/services/threadService'

export const threadEventKeys = {
  events: (threadId: string, workspaceId: string) =>
    ['thread-events', threadId, workspaceId] as const,
}

export function useThreadEvents(
  threadId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadEventKeys.events(threadId, workspaceId),
    queryFn: () => threadService.listThreadEvents(threadId, workspaceId),
    enabled: Boolean(threadId) && Boolean(workspaceId) && options?.enabled !== false,
    refetchOnWindowFocus: false,
  })
}
```

- [ ] **Step 5: Create `hooks/use-chat-send.ts`**

```ts
import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { threadService } from '@/services/threadService'
import { apiUpload } from '@/lib/api-client'
import { threadEventKeys } from './use-thread-events'
import type { ChatAttachment, ThreadEvent } from '@/types/thread'

interface PendingFile {
  file: File
  uploading: boolean
  uploaded?: { filename: string; path: string; size: number }
  error?: string
}

export function useChatSend(threadId: string, workspaceId: string) {
  const queryClient = useQueryClient()
  const [isSending, setIsSending] = useState(false)
  const [executionId, setExecutionId] = useState<string | null>(null)

  const send = useCallback(async (message: string, files: File[] = []) => {
    if (!threadId || isSending) return null
    setIsSending(true)

    try {
      const attachments: ChatAttachment[] = []
      for (const file of files) {
        const result = await apiUpload<{ filename: string; path: string; size: number }>(
          'files/upload', file,
        )
        attachments.push({
          filename: result.filename,
          storage_ref: result.path,
          mime_type: file.type || 'application/octet-stream',
          size_bytes: result.size,
        })
      }

      // Optimistic: insert user_message event into cache
      const optimisticEvent: ThreadEvent = {
        id: `optimistic-${Date.now()}`,
        run_id: '',
        execution_id: '',
        sequence_no: -1,
        event_type: 'user_message',
        payload: { text: message, ...(attachments.length ? { attachments } : {}) },
        execution_status: 'running',
        created_at: new Date().toISOString(),
      }
      queryClient.setQueryData(
        threadEventKeys.events(threadId, workspaceId),
        (old: { events: ThreadEvent[]; total: number } | undefined) => ({
          events: [...(old?.events ?? []), optimisticEvent],
          total: (old?.total ?? 0) + 1,
        }),
      )

      const res = await threadService.sendChat(threadId, workspaceId, message, attachments)
      setExecutionId(res.execution_id)
      return res
    } finally {
      setIsSending(false)
    }
  }, [threadId, workspaceId, isSending, queryClient])

  return { send, isSending, executionId }
}
```

- [ ] **Step 6: Create `hooks/use-chat-stream.ts`**

```ts
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useExecutionStream } from './use-execution-stream'
import { threadEventKeys } from './use-thread-events'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'
import type { ThreadEvent } from '@/types/thread'

export function useChatStream(
  executionId: string | null,
  threadId: string,
  workspaceId: string,
) {
  const queryClient = useQueryClient()
  const { events, status } = useExecutionStream({
    executionId: executionId || '',
    enabled: Boolean(executionId),
  })

  const lastSeenSeqRef = useRef(-1)

  useEffect(() => {
    if (!executionId || !events.length) return

    const newEvents = events.filter((e) => e.sequence_no > lastSeenSeqRef.current)
    if (!newEvents.length) return

    lastSeenSeqRef.current = Math.max(...newEvents.map((e) => e.sequence_no))

    queryClient.setQueryData(
      threadEventKeys.events(threadId, workspaceId),
      (old: { events: ThreadEvent[]; total: number } | undefined) => {
        const existing = old?.events ?? []
        const mapped: ThreadEvent[] = newEvents.map((e) => ({
          id: e.id || `stream-${e.sequence_no}`,
          run_id: '',
          execution_id: executionId,
          sequence_no: e.sequence_no,
          event_type: e.event_type,
          payload: e.payload,
          execution_status: status || 'running',
          created_at: e.created_at || new Date().toISOString(),
        }))
        return { events: [...existing, ...mapped], total: (old?.total ?? 0) + mapped.length }
      },
    )
  }, [events, executionId, threadId, workspaceId, status, queryClient])

  // Invalidate on completion to get final persisted state
  const prevStatusRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevStatusRef.current
    prevStatusRef.current = status
    if (
      prev && !TERMINAL_EXECUTION_STATUSES.includes(prev as never) &&
      status && TERMINAL_EXECUTION_STATUSES.includes(status as never)
    ) {
      lastSeenSeqRef.current = -1
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: threadEventKeys.events(threadId, workspaceId),
        })
      }, 500)
    }
  }, [status, threadId, workspaceId, queryClient])

  const isExecuting = Boolean(
    executionId && status && !TERMINAL_EXECUTION_STATUSES.includes(status as never),
  )

  return { isExecuting, status }
}
```

- [ ] **Step 7: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expect errors only from deleted files that still have consumers (fixed in Task 6).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: add frontend types, service, and hooks for chat event system

- ThreadEvent type replaces ThreadMessage
- threadService.listThreadEvents and sendChat replace message methods
- useThreadEvents, useChatSend, useChatStream hooks for data/mutation/streaming"
```

---

## Task 6: Frontend — ChatPanel Component System

**Files:**
- Create: `frontend/components/chat/AttachmentChip.tsx`
- Create: `frontend/components/chat/ChatFilePreview.tsx`
- Create: `frontend/components/chat/ChatEventBubble.tsx`
- Create: `frontend/components/chat/ChatInput.tsx`
- Create: `frontend/components/chat/ChatHistory.tsx`
- Create: `frontend/components/chat/ThreadSidebar.tsx`
- Create: `frontend/components/chat/ChatPanel.tsx`

Build bottom-up: smallest components first, then compose.

- [ ] **Step 1: Create `AttachmentChip.tsx`**

```tsx
'use client'

import { X, FileIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface AttachmentChipProps {
  filename: string
  mimeType: string
  sizeBytes: number
  uploading?: boolean
  onRemove?: () => void
}

export function AttachmentChip({ filename, mimeType, sizeBytes, uploading, onRemove }: AttachmentChipProps) {
  const sizeLabel = sizeBytes < 1024 * 1024
    ? `${(sizeBytes / 1024).toFixed(0)} KB`
    : `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`

  return (
    <div className={cn(
      'inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs',
      uploading && 'opacity-60',
    )}>
      <FileIcon className="h-3 w-3 text-[var(--text-muted)]" />
      <span className="max-w-[120px] truncate text-[var(--text-primary)]">{filename}</span>
      <span className="text-[var(--text-muted)]">{sizeLabel}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} className="ml-0.5 rounded p-0.5 hover:bg-[var(--surface-3)]">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create `ChatFilePreview.tsx`**

```tsx
'use client'

import { FileIcon, Download, Expand } from 'lucide-react'
import { useState } from 'react'
import { API_BASE } from '@/lib/api-client'

interface ChatFilePreviewProps {
  filename: string
  storageRef: string
  mimeType: string
  sizeBytes: number
}

function isImage(mime: string) { return mime.startsWith('image/') }
function isText(mime: string) {
  return mime.startsWith('text/') || mime === 'application/json' ||
    ['application/javascript', 'application/typescript', 'application/xml'].includes(mime)
}

export function ChatFilePreview({ filename, storageRef, mimeType, sizeBytes }: ChatFilePreviewProps) {
  const [expanded, setExpanded] = useState(false)
  const rawUrl = `${API_BASE}/files/read/${encodeURIComponent(filename)}?mode=raw`
  const sizeLabel = sizeBytes < 1024 * 1024
    ? `${(sizeBytes / 1024).toFixed(0)} KB`
    : `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`

  if (isImage(mimeType)) {
    return (
      <div className="mt-2 max-w-sm">
        <img
          src={rawUrl}
          alt={filename}
          className="max-h-64 rounded-md border border-[var(--border)] object-contain"
          loading="lazy"
        />
        <p className="mt-1 text-xs text-[var(--text-muted)]">{filename} ({sizeLabel})</p>
      </div>
    )
  }

  if (isText(mimeType)) {
    return (
      <div className="mt-2 max-w-md">
        <div className="flex items-center justify-between rounded-t-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-1.5">
          <span className="text-xs font-medium text-[var(--text-primary)]">{filename}</span>
          <span className="text-xs text-[var(--text-muted)]">{sizeLabel}</span>
        </div>
        <div className="rounded-b-md border border-t-0 border-[var(--border)] bg-[var(--surface-2)] p-3">
          <p className="text-xs text-[var(--text-muted)]">Text file — preview in development</p>
        </div>
      </div>
    )
  }

  return (
    <a
      href={rawUrl}
      download={filename}
      className="mt-2 inline-flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs hover:bg-[var(--surface-3)]"
    >
      <FileIcon className="h-4 w-4 text-[var(--text-muted)]" />
      <span className="text-[var(--text-primary)]">{filename}</span>
      <span className="text-[var(--text-muted)]">{sizeLabel}</span>
      <Download className="h-3 w-3 text-[var(--text-muted)]" />
    </a>
  )
}
```

- [ ] **Step 3: Create `ChatEventBubble.tsx`**

Event type → visual bubble mapping. Reference: spec section 5.5.

```tsx
'use client'

import { Bot, User, Wrench, AlertCircle, ChevronDown, Loader2, CheckCircle, XCircle, Package } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { cn } from '@/lib/utils'
import { ChatFilePreview } from './ChatFilePreview'
import type { ThreadEvent } from '@/types/thread'

interface ChatEventBubbleProps {
  event: ThreadEvent
}

export function ChatEventBubble({ event }: ChatEventBubbleProps) {
  const { event_type, payload } = event
  const [collapsed, setCollapsed] = useState(true)

  if (event_type === 'user_message') {
    const text = (payload.text as string) || ''
    const attachments = (payload.attachments as Array<{
      filename: string; storage_ref: string; mime_type: string; size_bytes: number
    }>) || []

    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] rounded-lg bg-[var(--skill-brand-600)] px-4 py-3 text-white">
          <p className="whitespace-pre-wrap break-words text-sm">{text}</p>
          {attachments.map((a) => (
            <ChatFilePreview key={a.storage_ref} filename={a.filename} storageRef={a.storage_ref} mimeType={a.mime_type} sizeBytes={a.size_bytes} />
          ))}
          <span className="mt-1 block text-xs opacity-70">
            {new Date(event.created_at).toLocaleTimeString()}
          </span>
        </div>
      </div>
    )
  }

  if (event_type === 'assistant_text') {
    const text = (payload.text as string) || (payload.delta as string) || ''
    return (
      <div className="flex justify-start">
        <div className="flex max-w-[70%] gap-3 rounded-lg bg-[var(--surface-2)] px-4 py-3">
          <Bot className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
          <div className="min-w-0 flex-1">
            <div className="prose prose-sm max-w-none break-words text-sm text-[var(--text-primary)]">
              <ReactMarkdown>{text}</ReactMarkdown>
            </div>
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              {new Date(event.created_at).toLocaleTimeString()}
            </span>
          </div>
        </div>
      </div>
    )
  }

  if (event_type === 'thinking') {
    return (
      <button type="button" onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
        <ChevronDown className={cn('h-3 w-3 transition-transform', !collapsed && 'rotate-180')} />
        Thinking...
        {!collapsed && (
          <div className="ml-2 max-w-md rounded bg-[var(--surface-2)] p-2 text-left text-xs">
            {(payload.text as string) || ''}
          </div>
        )}
      </button>
    )
  }

  if (event_type === 'tool_use_start') {
    const name = (payload.name as string) || 'tool'
    return (
      <button type="button" onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs">
        <Wrench className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="font-medium text-[var(--text-primary)]">{name}</span>
        <Loader2 className="h-3 w-3 animate-spin text-[var(--text-muted)]" />
        <ChevronDown className={cn('h-3 w-3 transition-transform', !collapsed && 'rotate-180')} />
        {!collapsed && (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[var(--text-muted)]">
            {JSON.stringify(payload.input, null, 2)}
          </pre>
        )}
      </button>
    )
  }

  if (event_type === 'tool_use_end') {
    const name = (payload.name as string) || 'tool'
    const success = payload.success !== false
    return (
      <button type="button" onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs">
        <Wrench className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="font-medium text-[var(--text-primary)]">{name}</span>
        {success ? <CheckCircle className="h-3 w-3 text-green-500" /> : <XCircle className="h-3 w-3 text-red-500" />}
        {!collapsed && (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[var(--text-muted)]">
            {typeof payload.output === 'string' ? payload.output : JSON.stringify(payload.output, null, 2)}
          </pre>
        )}
      </button>
    )
  }

  if (event_type === 'error') {
    return (
      <div className="rounded-md border border-red-500/20 bg-red-500/5 px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-red-400">
          <AlertCircle className="h-4 w-4" />
          <span>{(payload.message as string) || 'Error'}</span>
        </div>
        {payload.trace && (
          <button type="button" onClick={() => setCollapsed(!collapsed)} className="mt-1 text-xs text-red-400/70">
            {collapsed ? 'Show trace' : 'Hide trace'}
            {!collapsed && <pre className="mt-1 max-h-40 overflow-auto">{payload.trace as string}</pre>}
          </button>
        )}
      </div>
    )
  }

  if (event_type === 'artifact_created') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs">
        <Package className="h-3 w-3 text-[var(--text-muted)]" />
        <span className="text-[var(--text-primary)]">Artifact: {(payload.name as string) || 'output'}</span>
      </div>
    )
  }

  if (event_type === 'execution_started' || event_type === 'execution_completed') {
    const isComplete = event_type === 'execution_completed'
    const terminalStatus = (payload.terminal_status as string) || event.execution_status
    return (
      <div className="flex justify-center">
        <span className={cn(
          'rounded-full px-3 py-0.5 text-[10px] font-medium',
          isComplete && terminalStatus === 'succeeded' && 'bg-green-500/10 text-green-500',
          isComplete && terminalStatus !== 'succeeded' && 'bg-red-500/10 text-red-400',
          !isComplete && 'bg-[var(--surface-3)] text-[var(--text-muted)]',
        )}>
          {isComplete ? `Execution ${terminalStatus}` : 'Execution started'}
        </span>
      </div>
    )
  }

  // execution_status_change, copilot_* → ignore
  return null
}
```

- [ ] **Step 4: Create `ChatInput.tsx`**

```tsx
'use client'

import { Paperclip, Send, Loader2 } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AttachmentChip } from './AttachmentChip'
import { useTranslation } from '@/lib/i18n'
import { ALLOWED_MIME_TYPES, MAX_FILE_SIZE } from '@/lib/core/constants/upload-limits'

interface ChatInputProps {
  onSend: (message: string, files: File[]) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    if (!text.trim() && files.length === 0) return
    onSend(text.trim(), files)
    setText('')
    setFiles([])
  }, [text, files, onSend])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const addFiles = (newFiles: FileList | File[]) => {
    const valid = Array.from(newFiles).filter(
      (f) => f.size <= MAX_FILE_SIZE && ALLOWED_MIME_TYPES.includes(f.type),
    )
    setFiles((prev) => [...prev, ...valid].slice(0, 10))
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  return (
    <div
      className="border-t border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-3"
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <AttachmentChip
              key={`${f.name}-${i}`}
              filename={f.name}
              mimeType={f.type}
              sizeBytes={f.size}
              onRemove={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
            />
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.describeHelpNeeded')}
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--skill-brand-600)]"
        />
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }}
        />
        <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} disabled={disabled} className="h-9 w-9 p-0">
          <Paperclip className="h-4 w-4" />
        </Button>
        <Button onClick={handleSend} disabled={disabled || (!text.trim() && files.length === 0)} className="h-9 gap-1.5">
          {disabled ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create `ChatHistory.tsx`**

```tsx
'use client'

import { useEffect, useRef } from 'react'
import { Loader2 } from 'lucide-react'
import { ChatEventBubble } from './ChatEventBubble'
import { useTranslation } from '@/lib/i18n'
import type { ThreadEvent } from '@/types/thread'

interface ChatHistoryProps {
  events: ThreadEvent[]
  isLoading?: boolean
}

const IGNORED_EVENTS = new Set(['execution_status_change', 'approval_requested', 'approval_resolved'])

export function ChatHistory({ events, isLoading }: ChatHistoryProps) {
  const { t } = useTranslation()
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  const visible = events.filter((e) => !IGNORED_EVENTS.has(e.event_type) && !e.event_type.startsWith('copilot_'))

  if (visible.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">{t('chat.noMessages')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 px-6 py-4">
      {visible.map((event) => (
        <ChatEventBubble key={event.id} event={event} />
      ))}
      <div ref={endRef} />
    </div>
  )
}
```

- [ ] **Step 6: Create `ThreadSidebar.tsx`**

```tsx
'use client'

import { Plus, Loader2, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { Thread } from '@/types/thread'

interface ThreadSidebarProps {
  threads: Thread[]
  activeThreadId?: string
  onSelect: (threadId: string) => void
  onCreate: () => void
  isLoading?: boolean
  isCreating?: boolean
}

export function ThreadSidebar({
  threads, activeThreadId, onSelect, onCreate, isLoading, isCreating,
}: ThreadSidebarProps) {
  const { t } = useTranslation()

  return (
    <div className="flex w-64 flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('agents.detail.tabs.chat')}</h3>
        <Button size="sm" variant="ghost" onClick={onCreate} disabled={isCreating} className="h-7 w-7 p-0">
          {isCreating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> {t('common.loading')}
          </div>
        ) : threads.length === 0 ? (
          <p className="py-6 text-center text-xs text-[var(--text-muted)]">No threads yet</p>
        ) : (
          threads.map((thread) => (
            <button
              key={thread.id}
              type="button"
              onClick={() => onSelect(thread.id)}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
                thread.id === activeThreadId
                  ? 'bg-[var(--surface-3)] text-[var(--text-primary)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--surface-2)]',
              )}
            >
              <MessageSquare className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="truncate">{thread.title || 'Untitled'}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 7: Create `ChatPanel.tsx`**

```tsx
'use client'

import { useCallback } from 'react'
import { MessageSquare, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ThreadSidebar } from './ThreadSidebar'
import { ChatHistory } from './ChatHistory'
import { ChatInput } from './ChatInput'
import { useThreads, useCreateThread } from '@/hooks/queries/threads'
import { useThreadEvents } from '@/hooks/use-thread-events'
import { useChatSend } from '@/hooks/use-chat-send'
import { useChatStream } from '@/hooks/use-chat-stream'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

interface ChatPanelProps {
  agentId: string
  workspaceId: string
  threadId?: string
  onThreadChange?: (id: string) => void
  showThreadSidebar?: boolean
  className?: string
}

export function ChatPanel({
  agentId, workspaceId, threadId, onThreadChange, showThreadSidebar = true, className,
}: ChatPanelProps) {
  const { t } = useTranslation()
  const { data: threads = [], isLoading: threadsLoading } = useThreads(agentId, workspaceId)
  const createThread = useCreateThread()

  const { data: eventsData, isLoading: eventsLoading } = useThreadEvents(
    threadId || '', workspaceId, { enabled: Boolean(threadId) },
  )

  const { send, isSending, executionId } = useChatSend(threadId || '', workspaceId)
  const { isExecuting } = useChatStream(executionId, threadId || '', workspaceId)

  const handleCreateThread = useCallback(async () => {
    const thread = await createThread.mutateAsync({
      agent_id: agentId,
      workspace_id: workspaceId,
    })
    onThreadChange?.(thread.id)
  }, [agentId, workspaceId, createThread, onThreadChange])

  const handleSend = useCallback((message: string, files: File[]) => {
    send(message, files)
  }, [send])

  return (
    <div className={cn('flex h-full', className)}>
      {showThreadSidebar && (
        <ThreadSidebar
          threads={threads}
          activeThreadId={threadId}
          onSelect={(id) => onThreadChange?.(id)}
          onCreate={handleCreateThread}
          isLoading={threadsLoading}
          isCreating={createThread.isPending}
        />
      )}

      <div className="flex flex-1 flex-col">
        {!threadId ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <MessageSquare className="h-12 w-12 text-[var(--text-muted)]" />
            <p className="text-sm text-[var(--text-muted)]">{t('agents.detail.startChat')}</p>
            <Button onClick={handleCreateThread} disabled={createThread.isPending}>
              <Plus className="mr-1.5 h-4 w-4" /> {t('chat.newChat')}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              <ChatHistory events={eventsData?.events ?? []} isLoading={eventsLoading} />
            </div>
            <ChatInput onSend={handleSend} disabled={isSending || isExecuting} />
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: add ChatPanel component system

ChatPanel, ChatHistory, ChatEventBubble, ChatInput, ChatFilePreview,
AttachmentChip, ThreadSidebar — complete chat UI rendering execution
events as conversation."
```

---

## Task 7: Frontend — Wire Up & Delete Old Code

**Files:**
- Modify: `frontend/app/agents/[agentId]/page.tsx` (replace AgentChatTab with ChatPanel)
- Delete: `frontend/components/agents/agent-chat-tab.tsx`
- Delete: `frontend/components/threads/conversation-view.tsx`
- Delete: `frontend/components/threads/thread-list.tsx`
- Delete: `frontend/hooks/use-agent-chat.ts`

- [ ] **Step 1: Replace AgentChatTab with ChatPanel in agent detail page**

In `frontend/app/agents/[agentId]/page.tsx`, replace the `AgentChatTab` import and usage:

```tsx
import { ChatPanel } from '@/components/chat/ChatPanel'

// Replace: <AgentChatTab agentId={agentId} threadId={threadId} />
// With:
<ChatPanel
  agentId={agentId}
  workspaceId={workspaceId}
  threadId={threadId}
  onThreadChange={(id) => router.push(`/agents/${agentId}?tab=chat&thread=${id}`)}
/>
```

Note: `workspaceId` needs to be resolved in the page component. Check how other tabs get it — likely from `useWorkspaces()` hook. Add if not already present.

- [ ] **Step 2: Delete old files**

```bash
rm frontend/components/agents/agent-chat-tab.tsx
rm frontend/components/threads/conversation-view.tsx
rm frontend/components/threads/thread-list.tsx
rm frontend/hooks/use-agent-chat.ts
```

- [ ] **Step 3: Clean up dangling imports**

Search for any remaining imports of deleted modules:

```bash
cd frontend && grep -r "agent-chat-tab\|conversation-view\|thread-list\|use-agent-chat" --include="*.ts" --include="*.tsx" -l
```

Fix any found references.

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 5: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: replace AgentChatTab with ChatPanel, delete old chat code

AgentChatTab, conversation-view, thread-list, use-agent-chat deleted.
ChatPanel now serves as the chat tab in agent detail page."
```

---

## Task 8: Integration Verification

- [ ] **Step 1: Start backend**

```bash
cd backend && uv run uvicorn app.main:app --reload
```

Verify no startup errors. Check logs for missing subscriber warnings.

- [ ] **Step 2: Start frontend**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: Test golden path in browser**

1. Navigate to an agent detail page → Chat tab
2. Thread sidebar should load existing threads (or show empty state)
3. Create a new thread
4. Type a message and send
5. Verify: user message appears as right-aligned bubble
6. Verify: execution events stream in (assistant_text, tool_use_start/end, etc.)
7. Verify: execution_completed indicator appears when done

- [ ] **Step 4: Test file upload**

1. Attach a file via the paperclip button
2. Verify attachment chip appears
3. Send message with attachment
4. Verify: user_message bubble shows file preview

- [ ] **Step 5: Test thread switching**

1. Create multiple threads
2. Switch between them
3. Verify history loads correctly for each

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: integration fixes from manual testing"
```
