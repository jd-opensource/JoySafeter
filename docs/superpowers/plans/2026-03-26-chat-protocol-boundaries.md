# Chat Protocol Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Chat UI unified while refactoring `/ws/chat` so protocol control flow is explicit, `skill_creator` is isolated as an extension workflow, and stop/cancel is `request_id`-first.

**Architecture:** Introduce a typed websocket transport layer (`chat.start` + optional `extension.kind`), parse and validate frames before task creation, map parsed frames into explicit business commands, then move task lifecycle ownership into a supervisor so every request has a guaranteed terminal outcome. Frontend pages continue to share the chat UI, but they stop sending `metadata.mode` and instead build typed requests through the shared chat websocket client.

**Tech Stack:** FastAPI WebSocket, Pydantic, asyncio tasks, existing LangGraph stream helpers, React hooks, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-chat-protocol-boundaries-design.md`

---

### Task 1: Add Typed Chat Transport Parsing

**Files:**
- Create: `backend/app/websocket/chat_protocol.py`
- Test: `backend/tests/test_api/test_chat_protocol.py`
- Modify: `backend/app/websocket/chat_ws_handler.py`

- [ ] **Step 1: Write the failing parser tests**

```python
from app.websocket.chat_protocol import (
    ChatProtocolError,
    parse_client_frame,
    ParsedChatStartFrame,
)


def test_parse_standard_chat_start_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-1",
            "thread_id": None,
            "graph_id": None,
            "input": {"message": "hello", "files": []},
            "extension": None,
            "metadata": {},
        }
    )

    assert isinstance(parsed, ParsedChatStartFrame)
    assert parsed.request_id == "req-1"
    assert parsed.input.message == "hello"
    assert parsed.extension is None


def test_parse_skill_creator_extension_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-2",
            "input": {"message": "build a skill", "files": []},
            "extension": {
                "kind": "skill_creator",
                "run_id": "123e4567-e89b-12d3-a456-426614174000",
                "edit_skill_id": "skill-42",
            },
            "metadata": {},
        }
    )

    assert parsed.extension is not None
    assert parsed.extension.kind == "skill_creator"
    assert parsed.extension.edit_skill_id == "skill-42"


def test_reserved_metadata_control_keys_are_rejected():
    try:
        parse_client_frame(
            {
                "type": "chat.start",
                "request_id": "req-3",
                "input": {"message": "hello"},
                "extension": None,
                "metadata": {"mode": "apk-vulnerability"},
            }
        )
    except ChatProtocolError as exc:
        assert exc.message == "reserved metadata keys are not allowed"
        assert exc.request_id == "req-3"
    else:
        raise AssertionError("expected ChatProtocolError")
```

- [ ] **Step 2: Run the parser tests to verify they fail**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.websocket.chat_protocol` or missing parser symbols.

- [ ] **Step 3: Implement `chat_protocol.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


RESERVED_METADATA_KEYS = {"mode", "run_id", "edit_skill_id", "extension", "kind"}


@dataclass(frozen=True)
class ChatProtocolError(Exception):
    message: str
    request_id: str | None = None


@dataclass(frozen=True)
class ParsedChatInput:
    message: str
    files: list[dict[str, Any]]


@dataclass(frozen=True)
class ParsedSkillCreatorExtension:
    kind: Literal["skill_creator"]
    run_id: str | None
    edit_skill_id: str | None


@dataclass(frozen=True)
class ParsedChatStartFrame:
    request_id: str
    thread_id: str | None
    graph_id: str | None
    input: ParsedChatInput
    extension: ParsedSkillCreatorExtension | None
    metadata: dict[str, Any]


def parse_client_frame(frame: dict[str, Any]) -> ParsedChatStartFrame | dict[str, Any]:
    frame_type = str(frame.get("type") or "")
    if frame_type not in {"chat.start", "chat.resume", "chat.stop", "chat"}:
        raise ChatProtocolError(f"unknown frame type: {frame_type or '<missing>'}")
    if frame_type in {"chat.start", "chat"}:
        metadata = frame.get("metadata") if isinstance(frame.get("metadata"), dict) else {}
        reserved = RESERVED_METADATA_KEYS.intersection(metadata.keys())
        if reserved:
            raise ChatProtocolError(
                "reserved metadata keys are not allowed",
                request_id=str(frame.get("request_id") or "") or None,
            )
        ...
```

- [ ] **Step 4: Run the parser tests to verify they pass**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py -v
```

Expected: PASS with 3 passing tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/websocket/chat_protocol.py backend/tests/test_api/test_chat_protocol.py backend/app/websocket/chat_ws_handler.py
git commit -m "feat: add typed chat transport parser"
```

### Task 2: Map Parsed Frames Into Explicit Chat Commands

**Files:**
- Create: `backend/app/websocket/chat_commands.py`
- Modify: `backend/app/websocket/chat_ws_handler.py`
- Modify: `backend/app/schemas/chat.py`
- Test: `backend/tests/test_api/test_chat_ws_handler.py`
- Test: `backend/tests/test_schemas/test_chat.py`

- [ ] **Step 1: Write failing command-mapping tests**

```python
@pytest.mark.asyncio
async def test_chat_start_with_non_skill_extension_data_is_rejected_before_task_creation() -> None:
    handler, ws = make_handler()

    await handler._handle_frame(
        json.dumps(
            {
                "type": "chat.start",
                "request_id": "req-invalid",
                "input": {"message": "hello"},
                "extension": {"kind": "unknown"},
                "metadata": {},
            }
        )
    )

    assert ws.frames_of_type("ws_error") == [
        {"type": "ws_error", "request_id": "req-invalid", "message": "invalid extension kind"}
    ]
    assert "req-invalid" not in handler._tasks


@pytest.mark.asyncio
async def test_legacy_skill_creator_metadata_maps_to_skill_creator_command() -> None:
    handler, ws = make_handler()
    captured_command = None

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        nonlocal captured_command
        captured_command = payload

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn):
        await handler._handle_frame(
            json.dumps(
                {
                    "type": "chat",
                    "request_id": "req-legacy",
                    "message": "build a skill",
                    "metadata": {"mode": "skill_creator", "edit_skill_id": "skill-1"},
                }
            )
        )
        await handler._tasks["req-legacy"].task

    assert captured_command.mode == "skill_creator"
    assert captured_command.edit_skill_id == "skill-1"
    assert ws.sent == []
```

- [ ] **Step 2: Run the handler tests to verify they fail**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py -k "invalid_extension or legacy_skill_creator" -v
```

Expected: FAIL because the handler still constructs `ChatRequest` directly from loose frame data.

- [ ] **Step 3: Implement explicit command mapping**

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StandardChatTurnCommand:
    request_id: str
    message: str
    thread_id: str | None
    graph_id: str | None
    files: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SkillCreatorTurnCommand(StandardChatTurnCommand):
    run_id: str | None
    edit_skill_id: str | None


def build_chat_turn_command(parsed: ParsedChatStartFrame) -> StandardChatTurnCommand | SkillCreatorTurnCommand:
    if parsed.extension is None:
        return StandardChatTurnCommand(
            request_id=parsed.request_id,
            message=parsed.input.message,
            thread_id=parsed.thread_id,
            graph_id=parsed.graph_id,
            files=parsed.input.files,
            metadata=parsed.metadata,
        )
    return SkillCreatorTurnCommand(
        request_id=parsed.request_id,
        message=parsed.input.message,
        thread_id=parsed.thread_id,
        graph_id=parsed.graph_id,
        files=parsed.input.files,
        metadata=parsed.metadata,
        run_id=parsed.extension.run_id,
        edit_skill_id=parsed.extension.edit_skill_id,
    )
```

- [ ] **Step 4: Keep `ChatRequest` generic during migration**

```python
class ChatRequest(PydanticBaseModel):
    message: str = Field(..., description="用户消息")
    thread_id: Optional[str] = Field(None, description="会话线程ID，不提供则创建新会话")
    graph_id: Optional[uuid.UUID] = Field(None, description="图ID，使用指定的图进行对话")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
```

Use the command object, not `metadata`, to decide when to append `skill_creator` run state and edit context.

- [ ] **Step 5: Run the handler and schema tests**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py backend/tests/test_schemas/test_chat.py -v
```

Expected: PASS for the new mapping tests and updated schema tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/websocket/chat_commands.py backend/app/websocket/chat_ws_handler.py backend/app/schemas/chat.py backend/tests/test_api/test_chat_ws_handler.py backend/tests/test_schemas/test_chat.py
git commit -m "refactor: isolate chat command mapping from metadata"
```

### Task 3: Extract Task Supervision And Guarantee Terminal Outcomes

**Files:**
- Create: `backend/app/websocket/chat_task_supervisor.py`
- Create: `backend/app/websocket/chat_turn_executor.py`
- Modify: `backend/app/websocket/chat_ws_handler.py`
- Test: `backend/tests/test_api/test_chat_ws_handler.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
@pytest.mark.asyncio
async def test_stop_by_request_id_cancels_turn_before_thread_assignment() -> None:
    handler, ws = make_handler()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        entered.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn):
        await handler._handle_frame(
            json.dumps(
                {
                    "type": "chat.start",
                    "request_id": "req-stop-early",
                    "input": {"message": "hello"},
                    "extension": None,
                    "metadata": {},
                }
            )
        )
        await entered.wait()
        await handler._handle_frame(json.dumps({"type": "chat.stop", "request_id": "req-stop-early"}))
        await asyncio.sleep(0)

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_protocol_error_does_not_register_task() -> None:
    handler, ws = make_handler()

    await handler._handle_frame(
        json.dumps(
            {
                "type": "chat.start",
                "request_id": "req-bad",
                "input": {"message": ""},
                "extension": None,
                "metadata": {},
            }
        )
    )

    assert ws.frames_of_type("ws_error")
    assert handler._tasks == {}
```

- [ ] **Step 2: Run the lifecycle tests to verify they fail**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py -k "stop_by_request_id or protocol_error_does_not_register_task" -v
```

Expected: FAIL because lifecycle logic is still embedded in `ChatWsHandler`.

- [ ] **Step 3: Implement `ChatTaskSupervisor`**

```python
@dataclass
class ChatTaskEntry:
    request_id: str
    thread_id: str | None
    task: asyncio.Task[Any]
    heartbeat_task: asyncio.Task[Any] | None = None
    run_id: uuid_lib.UUID | None = None
    persist_on_disconnect: bool = False


class ChatTaskSupervisor:
    def __init__(self) -> None:
        self._tasks: dict[str, ChatTaskEntry] = {}
        self._thread_to_request: dict[str, str] = {}

    def register(self, entry: ChatTaskEntry) -> None:
        self._tasks[entry.request_id] = entry
        if entry.thread_id:
            self._thread_to_request[entry.thread_id] = entry.request_id

    async def stop_by_request_id(self, request_id: str) -> None:
        entry = self._tasks.get(request_id)
        if entry is None:
            return
        if entry.thread_id:
            await task_manager.stop_task(entry.thread_id)
        entry.task.cancel()

    async def finalize(self, request_id: str) -> ChatTaskEntry | None:
        entry = self._tasks.pop(request_id, None)
        if entry and entry.thread_id:
            self._thread_to_request.pop(entry.thread_id, None)
        return entry
```

- [ ] **Step 4: Implement `ChatTurnExecutor` and wire it into the handler**

```python
class ChatTurnExecutor:
    async def run_standard_turn(self, command: StandardChatTurnCommand) -> None:
        ...

    async def run_skill_creator_turn(self, command: SkillCreatorTurnCommand) -> None:
        ...
```

`ChatWsHandler` should:

- parse frame
- build command
- register a task through `ChatTaskSupervisor`
- delegate actual turn execution to `ChatTurnExecutor`
- funnel stop/disconnect/finalize through the supervisor

- [ ] **Step 5: Run the full backend handler test file**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_ws_handler.py -v
```

Expected: PASS, including the two existing cancellation tests that are red today:
- `test_handle_stop_cancels_known_task`
- `test_cancel_all_tasks_on_disconnect`

- [ ] **Step 6: Commit**

```bash
git add backend/app/websocket/chat_task_supervisor.py backend/app/websocket/chat_turn_executor.py backend/app/websocket/chat_ws_handler.py backend/tests/test_api/test_chat_ws_handler.py
git commit -m "refactor: centralize chat task supervision"
```

### Task 4: Migrate Frontend Chat Transport To Explicit Requests

**Files:**
- Modify: `frontend/lib/ws/chat/types.ts`
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`
- Modify: `frontend/app/chat/hooks/useChatWebSocket.ts`
- Modify: `frontend/app/chat/ChatLayout.tsx`
- Modify: `frontend/hooks/use-skill-creator-run.ts`
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/services/workspaceChatWsService.ts`
- Test: `frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts`
- Test: `frontend/app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts`

- [ ] **Step 1: Write the failing frontend transport tests**

```ts
it('sendMessage sends chat.start without extension for standard chat', async () => {
  const { utils, ws } = await renderConnectedHook()

  void utils.result.current.sendMessage({
    input: { message: 'hello' },
    extension: null,
  })
  await Promise.resolve()

  const frame = JSON.parse(ws.sent[ws.sent.length - 1])
  expect(frame.type).toBe('chat.start')
  expect(frame.extension).toBeNull()
  expect(frame.metadata).toEqual({})
})

it('skill creator sends explicit skill_creator extension', async () => {
  const client = getChatWsClient()
  void client.sendChat({
    input: { message: 'build a skill' },
    extension: { kind: 'skill_creator', editSkillId: 'skill-7' },
  })
  await Promise.resolve()

  const frame = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])
  expect(frame.extension).toMatchObject({ kind: 'skill_creator', edit_skill_id: 'skill-7' })
})

it('stopMessage stops by requestId before threadId exists', async () => {
  const { utils, ws } = await renderConnectedHook()

  void utils.result.current.sendMessage({ input: { message: 'hello' }, extension: null })
  await Promise.resolve()
  const startFrame = JSON.parse(ws.sent[ws.sent.length - 1])

  utils.result.current.stopMessage(startFrame.request_id)

  const stopFrame = JSON.parse(ws.sent[ws.sent.length - 1])
  expect(stopFrame).toMatchObject({ type: 'chat.stop', request_id: startFrame.request_id })
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run:

```bash
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm test -- app/chat/hooks/__tests__/useChatWebSocket.test.ts app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts
```

Expected: FAIL because the client still emits `type: "chat"` with top-level `message` and stop is still `threadId`-first.

- [ ] **Step 3: Update chat websocket request types**

```ts
export interface ChatSendInput {
  message: string
  files?: Array<{ filename: string; path: string; size: number }>
}

export interface SkillCreatorExtension {
  kind: 'skill_creator'
  runId?: string | null
  editSkillId?: string | null
}

export interface ChatSendParams {
  requestId?: string
  threadId?: string | null
  graphId?: string | null
  input: ChatSendInput
  extension?: SkillCreatorExtension | null
  metadata?: Record<string, unknown>
  onEvent?: (evt: ChatStreamEvent) => void
  onAccepted?: (evt: IncomingChatAcceptedEvent) => void
}
```

- [ ] **Step 4: Update the shared client and hooks**

```ts
this.sendFrame({
  type: 'chat.start',
  request_id: requestId,
  thread_id: params.threadId ?? null,
  graph_id: params.graphId ?? null,
  input: params.input,
  extension: params.extension ?? null,
  metadata: params.metadata ?? {},
})
```

In `useChatWebSocket.ts`:

```ts
const activeRequestIdRef = useRef<string | null>(null)

const stopMessage = useCallback((requestId: string | null) => {
  if (!requestId) return
  clientRef.current.stopByRequestId(requestId)
}, [])
```

In `ChatLayout.tsx`, standard chat sends:

```ts
await stream.sendMessage({
  input: {
    message: text,
    files: files?.map((f) => ({ filename: f.filename, path: f.path, size: f.size })),
  },
  threadId: messageOpts.threadId,
  graphId: messageOpts.graphId,
  extension: null,
  metadata: {},
})
```

In `use-skill-creator-run.ts`, skill creator sends:

```ts
await clientRef.current.sendChat({
  requestId,
  threadId: projection.thread_id,
  graphId: graphId,
  input: { message: userPrompt },
  extension: {
    kind: 'skill_creator',
    runId: pendingRunId,
    editSkillId: effectiveEditSkillId,
  },
  metadata: {},
  onAccepted,
  onEvent,
})
```

- [ ] **Step 5: Run the frontend tests and type-check**

Run:

```bash
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm test -- app/chat/hooks/__tests__/useChatWebSocket.test.ts app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm type-check
```

Expected: PASS for both test files and `tsc --noEmit`.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/ws/chat/types.ts frontend/lib/ws/chat/chatWsClient.ts frontend/app/chat/hooks/useChatWebSocket.ts frontend/app/chat/ChatLayout.tsx frontend/hooks/use-skill-creator-run.ts 'frontend/app/workspace/[workspaceId]/[agentId]/services/workspaceChatWsService.ts' frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts 'frontend/app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts'
git commit -m "refactor: move chat websocket requests to explicit extensions"
```

### Task 5: Remove Compatibility Paths And Finalize The Contract

**Files:**
- Modify: `backend/app/websocket/chat_protocol.py`
- Modify: `backend/app/websocket/chat_ws_handler.py`
- Modify: `backend/app/schemas/chat.py`
- Modify: `frontend/app/chat/ChatLayout.tsx`
- Modify: `frontend/hooks/use-skill-creator-run.ts`
- Test: `backend/tests/test_api/test_chat_protocol.py`
- Test: `backend/tests/test_api/test_chat_ws_handler.py`
- Test: `frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts`

- [ ] **Step 1: Write the failing compatibility-removal tests**

```python
def test_legacy_metadata_mode_is_rejected_after_cutover():
    with pytest.raises(ChatProtocolError) as exc_info:
        parse_client_frame(
            {
                "type": "chat",
                "request_id": "req-old",
                "message": "hello",
                "metadata": {"mode": "skill_creator"},
            }
        )

    assert exc_info.value.message == "legacy metadata control fields are no longer supported"
```

```ts
it('standard chat no longer sends metadata.mode after cutover', async () => {
  const { utils, ws } = await renderConnectedHook()

  void utils.result.current.sendMessage({
    input: { message: 'hello' },
    extension: null,
    metadata: {},
  })
  await Promise.resolve()

  const frame = JSON.parse(ws.sent[ws.sent.length - 1])
  expect(frame.metadata.mode).toBeUndefined()
})
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py backend/tests/test_api/test_chat_ws_handler.py -k "legacy_metadata" -v
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm test -- app/chat/hooks/__tests__/useChatWebSocket.test.ts
```

Expected: FAIL because legacy compatibility code still exists.

- [ ] **Step 3: Delete the compatibility logic**

```python
if frame_type == "chat":
    raise ChatProtocolError("legacy metadata control fields are no longer supported", request_id=request_id)
```

and remove:

- any `metadata.mode` fallback
- any `metadata.run_id` / `metadata.edit_skill_id` protocol mapping
- any `ChatRequest` fields that only existed for compatibility

- [ ] **Step 4: Run final verification**

Run:

```bash
SECRET_KEY=test-secret backend/.venv/bin/pytest backend/tests/test_api/test_chat_protocol.py backend/tests/test_api/test_chat_ws_handler.py backend/tests/test_schemas/test_chat.py -v
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm test -- app/chat/hooks/__tests__/useChatWebSocket.test.ts app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts
cd frontend && PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm type-check
```

Expected:
- backend targeted suites PASS
- frontend targeted suites PASS
- frontend type-check PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/websocket/chat_protocol.py backend/app/websocket/chat_ws_handler.py backend/app/schemas/chat.py backend/tests/test_api/test_chat_protocol.py backend/tests/test_api/test_chat_ws_handler.py backend/tests/test_schemas/test_chat.py frontend/app/chat/ChatLayout.tsx frontend/hooks/use-skill-creator-run.ts frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts
git commit -m "refactor: finalize explicit chat protocol boundaries"
```

## Self-Review

- Spec coverage:
  - typed extension protocol: Tasks 1, 2, 4, 5
  - backend parser / command factory / supervisor / executor split: Tasks 1, 2, 3
  - `request_id`-first stop semantics: Tasks 3 and 4
  - metadata control-field removal: Tasks 1 and 5
  - compatibility rollout and cleanup: Tasks 2 and 5
- Placeholder scan:
  - no `TODO` / `TBD` placeholders remain
  - every task has exact file paths, concrete tests, concrete commands
- Type consistency:
  - backend uses `ParsedChatStartFrame`, explicit command dataclasses, and `ChatTaskSupervisor`
  - frontend uses `ChatSendParams.input` and `extension`, not top-level `message` + `metadata.mode`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-03-26-chat-protocol-boundaries.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
