# Agent 文件 Preview 全流程重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the complex dual-path file preview system with incremental event-driven file tracking via a Proxy pattern on the sandbox backend.

**Architecture:** `FileTrackingProxy` wraps `PydanticSandboxAdapter`, intercepts write/edit/upload operations, emits `FileEvent` to `FileEventEmitter`. The SSE loop in `chat.py` drains events and pushes `file_event` SSE. Frontend builds `fileTree` from these events and uses `liveReadFile` for content.

**Tech Stack:** Python (FastAPI, LangGraph), TypeScript (Next.js, React), SSE streaming

**Spec:** `docs/superpowers/specs/2026-03-20-agent-file-preview-refactor-design.md`

---

### Task 1: Create `FileEventEmitter`

**Files:**
- Create: `backend/app/utils/file_event_emitter.py`
- Create: `backend/tests/test_utils/test_file_event_emitter.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_utils/test_file_event_emitter.py
from app.utils.file_event_emitter import FileEvent, FileEventEmitter


def test_emit_and_drain():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/hello.py", size=42)
    emitter.emit("edit", "/app/hello.py")
    events = emitter.drain()
    assert len(events) == 2
    assert events[0].action == "write"
    assert events[0].path == "/app/hello.py"
    assert events[0].size == 42
    assert events[1].action == "edit"
    assert events[1].size is None


def test_drain_empties_queue():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    emitter.drain()
    assert emitter.drain() == []


def test_drain_no_loss_under_interleave():
    """Simulate emit during drain - popleft loop should not lose events."""
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    emitter.emit("write", "/app/b.py")
    # drain first
    events = emitter.drain()
    assert len(events) == 2
    # emit after drain
    emitter.emit("write", "/app/c.py")
    events2 = emitter.drain()
    assert len(events2) == 1
    assert events2[0].path == "/app/c.py"


def test_file_event_has_timestamp():
    emitter = FileEventEmitter()
    emitter.emit("write", "/app/a.py")
    events = emitter.drain()
    assert events[0].timestamp > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_utils/test_file_event_emitter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.file_event_emitter'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/utils/file_event_emitter.py
"""File event emitter for real-time artifact preview during Agent execution."""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field


@dataclass
class FileEvent:
    """A single file operation event."""

    action: str  # "write" | "edit" | "delete"
    path: str
    size: int | None = None
    timestamp: float = field(default_factory=time.time)


class FileEventEmitter:
    """Thread-safe file event collector. Proxy emits, SSE loop drains."""

    def __init__(self) -> None:
        self._queue: collections.deque[FileEvent] = collections.deque()

    def emit(self, action: str, path: str, size: int | None = None) -> None:
        self._queue.append(FileEvent(action=action, path=path, size=size))

    def drain(self) -> list[FileEvent]:
        """Atomically pop all pending events. Uses popleft loop to avoid
        race between list()+clear() when emit() is called concurrently."""
        events: list[FileEvent] = []
        while self._queue:
            try:
                events.append(self._queue.popleft())
            except IndexError:
                break
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_utils/test_file_event_emitter.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/file_event_emitter.py backend/tests/test_utils/test_file_event_emitter.py
git commit -m "feat: add FileEventEmitter for real-time file tracking"
```

---

### Task 2: Create `FileTrackingProxy`

**Files:**
- Create: `backend/app/core/agent/backends/file_tracking_proxy.py`
- Create: `backend/tests/backends/test_file_tracking_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/backends/test_file_tracking_proxy.py
from unittest.mock import MagicMock

from deepagents.backends.protocol import EditResult, FileUploadResponse, WriteResult

from app.core.agent.backends.file_tracking_proxy import FileTrackingProxy
from app.utils.file_event_emitter import FileEventEmitter


def _make_mock_backend():
    backend = MagicMock()
    backend.id = "test-sandbox"
    backend.is_started.return_value = True
    return backend


def test_write_success_emits_event():
    backend = _make_mock_backend()
    backend.write.return_value = WriteResult(path="/app/hello.py", files_update=None)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.write("/app/hello.py", "print('hi')")
    assert result.path == "/app/hello.py"
    events = emitter.drain()
    assert len(events) == 1
    assert events[0].action == "write"
    assert events[0].path == "/app/hello.py"
    assert events[0].size == len("print('hi')".encode("utf-8"))


def test_write_error_does_not_emit():
    backend = _make_mock_backend()
    backend.write.return_value = WriteResult(error="File exists")
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.write("/app/hello.py", "x")
    assert result.error
    assert emitter.drain() == []


def test_edit_success_emits_event():
    backend = _make_mock_backend()
    backend.edit.return_value = EditResult(path="/app/hello.py", files_update=None, occurrences=1)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.edit("/app/hello.py", "old", "new")
    assert result.path == "/app/hello.py"
    events = emitter.drain()
    assert len(events) == 1
    assert events[0].action == "edit"


def test_write_overwrite_emits_write():
    backend = _make_mock_backend()
    backend.write_overwrite.return_value = WriteResult(path="/app/a.py", files_update=None)
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    proxy.write_overwrite("/app/a.py", "content")
    events = emitter.drain()
    assert events[0].action == "write"


def test_upload_files_emits_per_file():
    backend = _make_mock_backend()
    backend.upload_files.return_value = [
        FileUploadResponse(path="/app/a.py", error=None),
        FileUploadResponse(path="/app/b.py", error="fail"),
    ]
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    proxy.upload_files([("/app/a.py", b"aa"), ("/app/b.py", b"bb")])
    events = emitter.drain()
    # Only the successful upload emits
    assert len(events) == 1
    assert events[0].path == "/app/a.py"


def test_read_delegates_without_emit():
    backend = _make_mock_backend()
    backend.read.return_value = "file content"
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    result = proxy.read("/app/hello.py")
    assert result == "file content"
    assert emitter.drain() == []
    backend.read.assert_called_once_with("/app/hello.py")


def test_getattr_fallback():
    backend = _make_mock_backend()
    backend.some_new_method.return_value = "ok"
    emitter = FileEventEmitter()
    proxy = FileTrackingProxy(backend, emitter)

    assert proxy.some_new_method() == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/backends/test_file_tracking_proxy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# backend/app/core/agent/backends/file_tracking_proxy.py
"""Proxy that wraps SandboxBackendProtocol to emit file events on write operations."""

from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)

from app.utils.file_event_emitter import FileEventEmitter


class FileTrackingProxy(SandboxBackendProtocol):
    """Transparent proxy that intercepts write operations and emits file events.

    All non-write methods are delegated directly to the wrapped backend.
    Unknown methods are forwarded via __getattr__ for forward compatibility.
    """

    def __init__(self, backend: SandboxBackendProtocol, emitter: FileEventEmitter) -> None:
        self._backend = backend
        self._emitter = emitter

    # ── Write operations (intercepted) ──────────────────────────────────

    def write(self, file_path: str, content: str) -> WriteResult:
        result = self._backend.write(file_path, content)
        if not getattr(result, "error", None):
            self._emitter.emit("write", file_path, len(content.encode("utf-8")))
        return result

    def write_overwrite(self, file_path: str, content: str) -> WriteResult:
        result = self._backend.write_overwrite(file_path, content)
        if not getattr(result, "error", None):
            self._emitter.emit("write", file_path, len(content.encode("utf-8")))
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        result = self._backend.edit(file_path, old_string, new_string, replace_all)
        if not getattr(result, "error", None):
            self._emitter.emit("edit", file_path)
        return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = self._backend.upload_files(files)
        for (path, content), resp in zip(files, results):
            if not getattr(resp, "error", None):
                self._emitter.emit("write", path, len(content))
        return results

    # ── Read operations (delegated) ─────────────────────────────────────

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return self._backend.read(file_path, offset, limit)

    def ls_info(self, path: str) -> list[FileInfo]:
        return self._backend.ls_info(path)

    def execute(self, command: str) -> ExecuteResponse:
        return self._backend.execute(command)

    def grep_raw(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        return self._backend.grep_raw(pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return self._backend.glob_info(pattern, path)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._backend.download_files(paths)

    # ── Lifecycle (delegated) ───────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._backend.id

    def is_started(self) -> bool:
        return self._backend.is_started()

    def start(self) -> None:
        return self._backend.start()

    def stop(self) -> None:
        return self._backend.stop()

    def cleanup(self) -> None:
        return self._backend.cleanup()

    # ── Forward compatibility ───────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/backends/test_file_tracking_proxy.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/agent/backends/file_tracking_proxy.py backend/tests/backends/test_file_tracking_proxy.py
git commit -m "feat: add FileTrackingProxy for sandbox write interception"
```

---

### Task 3: Inject Proxy in `DeepAgentsGraphBuilder`

**Files:**
- Modify: `backend/app/core/graph/deep_agents_builder.py:38-53` (add `file_emitter` param, wrap backend)
- Modify: `backend/app/core/graph/graph_builder_factory.py:65-79` (pass `file_emitter` through)
- Modify: `backend/app/services/graph_service.py:734,841` (pass `file_emitter` through)

- [ ] **Step 1: Modify `DeepAgentsGraphBuilder.__init__` and `build()`**

In `backend/app/core/graph/deep_agents_builder.py`:

Add `file_emitter` to `__init__`:
```python
# In __init__, after self._node_builder line:
self._file_emitter: Optional[Any] = kwargs.pop("file_emitter", None)
```

In `build()`, after `self._shared_backend = await self._get_user_sandbox()` (line 50), add proxy wrapping:
```python
# Wrap with FileTrackingProxy for real-time file event tracking
if self._shared_backend and self._file_emitter:
    from app.core.agent.backends.file_tracking_proxy import FileTrackingProxy
    self._shared_backend = FileTrackingProxy(self._shared_backend, self._file_emitter)
    logger.info(f"{LOG_PREFIX} Wrapped backend with FileTrackingProxy")
```

- [ ] **Step 2: Pass `file_emitter` through `GraphBuilder`**

In `backend/app/core/graph/graph_builder_factory.py`:

Add to `GraphBuilder.__init__`:
```python
self.file_emitter = kwargs.pop("file_emitter", None)
```

In `_create_builder()`, pass to `DeepAgentsGraphBuilder`:
```python
return DeepAgentsGraphBuilder(
    self.graph, self.nodes, self.edges,
    self.llm_model, self.api_key, self.base_url,
    self.max_tokens, self.user_id, self.model_service,
    file_emitter=self.file_emitter,
)
```

- [ ] **Step 3: Pass `file_emitter` through `GraphService`**

In `backend/app/services/graph_service.py`:

Add `file_emitter` parameter to `create_default_deep_agents_graph()` and `create_graph_by_graph_id()` methods. Pass to `GraphBuilder(...)`:
```python
builder = GraphBuilder(
    ...,
    file_emitter=file_emitter,
)
```

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -x -q --timeout=30`
Expected: All existing tests pass (file_emitter defaults to None, no behavior change)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/graph/deep_agents_builder.py backend/app/core/graph/graph_builder_factory.py backend/app/services/graph_service.py
git commit -m "feat: thread file_emitter through graph builder chain"
```

---

### Task 4: Integrate emitter in `chat.py` SSE loop

**Files:**
- Modify: `backend/app/api/v1/chat.py:698-815` (create emitter, pass to graph, drain in SSE loop)

- [ ] **Step 1: Create emitter and pass to graph service**

In `chat.py`, inside `event_generator()` (around line 700), after `StreamState` and `StreamEventHandler` creation:

```python
from app.utils.file_event_emitter import FileEventEmitter

file_emitter = FileEventEmitter()
```

Pass `file_emitter` to `graph_service.create_default_deep_agents_graph(...)` and `graph_service.create_graph_by_graph_id(...)`:
```python
graph = await graph_service.create_default_deep_agents_graph(
    ...,
    file_emitter=file_emitter,
)
```

- [ ] **Step 2: Add drain loop after each SSE yield**

After the main event dispatch block (after line ~816, just before `# 5. 检查是否有中断`), add drain at the end of the `async for` loop body:

```python
                # Drain file events from proxy
                for file_evt in file_emitter.drain():
                    yield handler.format_sse("file_event", {
                        "action": file_evt.action,
                        "path": file_evt.path,
                        "size": file_evt.size,
                        "timestamp": file_evt.timestamp,
                    }, state.thread_id, state)
```

- [ ] **Step 3: Verify SSE format manually**

Run the backend, send a chat message that triggers file creation in sandbox, inspect SSE output for `file_event` type.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/chat.py
git commit -m "feat: emit file_event SSE from chat stream loop"
```

---

### Task 5: Remove old `_extract_files_changed` from backend

**Files:**
- Modify: `backend/app/utils/stream_event_handler.py:1017-1063` (delete `_FILE_WRITE_TOOLS` and `_extract_files_changed`)
- Modify: `backend/app/utils/stream_event_handler.py:674-688` (remove `files_changed` from `handle_tool_end`)

- [ ] **Step 1: Remove `_FILE_WRITE_TOOLS` and `_extract_files_changed`**

Delete lines 1017-1063 from `stream_event_handler.py` (the `_FILE_WRITE_TOOLS` frozenset and `_extract_files_changed` function).

- [ ] **Step 2: Remove `files_changed` from `handle_tool_end`**

In `handle_tool_end`, remove line 675:
```python
files_changed = _extract_files_changed(tool_name, output, record)
```

And remove `"files_changed": files_changed if files_changed else None,` from the payload dict (line 684).

- [ ] **Step 3: Run existing tests**

Run: `cd backend && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS (if any test references `files_changed`, update it)

- [ ] **Step 4: Commit**

```bash
git add backend/app/utils/stream_event_handler.py
git commit -m "refactor: remove _extract_files_changed, replaced by FileTrackingProxy"
```

---

### Task 6: Remove `artifacts_ready` from backend

**Files:**
- Modify: `backend/app/api/v1/chat.py:977-990` (remove `artifacts_ready` yield)

- [ ] **Step 1: Remove the `artifacts_ready` SSE yield**

In `chat.py` finally block, delete the `artifacts_ready` yield block (lines ~977-990):
```python
# DELETE THIS BLOCK:
if not state.interrupted:
    try:
        yield handler.format_sse(
            "artifacts_ready",
            { ... },
            thread_id,
        )
    except Exception:
        ...
```

Note: Keep the `ArtifactCollector.write_manifest()` call — it's used for history and may be needed by other features.

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/chat.py
git commit -m "refactor: remove artifacts_ready SSE event, replaced by file_event"
```

---

### Task 7: Frontend — handle `file_event` in `useBackendChatStream`

**Files:**
- Modify: `frontend/app/chat/hooks/useBackendChatStream.ts:197-237` (add `file_event` handler, remove `liveFiles`)
- Modify: `frontend/services/chatBackend.ts` (add `FileEventData` type if needed)

- [ ] **Step 1: Add `file_event` handler**

In `useBackendChatStream.ts`, add a new handler before the `tool_end` handler (around line 196):

```typescript
// Handle file_event - real-time file operation from sandbox
if (type === 'file_event') {
  const { action, path, size, timestamp: ts } = data as {
    action: string; path: string; size?: number; timestamp?: number
  }
  safeSetMessages(prev => prev.map(m => {
    if (m.id !== aiMsgId) return m
    const tree = { ...(m.metadata?.fileTree as Record<string, any> || {}) }
    if (action === 'delete') {
      delete tree[path]
    } else {
      tree[path] = { action, size, timestamp: ts }
    }
    return { ...m, metadata: { ...m.metadata, fileTree: tree } }
  }))
  return
}
```

- [ ] **Step 2: Remove `liveFiles` accumulation from `tool_end`**

In the `tool_end` handler (lines ~220-232), remove the `filesChanged` block:
```typescript
// DELETE THIS:
const filesChanged = toolData?.files_changed
if (filesChanged?.length) {
  const existing = (m.metadata?.liveFiles as ...) ?? []
  return { ...m, tool_calls: tools, metadata: { ...m.metadata, liveFiles: [...existing, ...filesChanged] } }
}
```

- [ ] **Step 3: Remove `artifacts_ready` handler**

Delete the `artifacts_ready` handler block (lines ~274-281).

- [ ] **Step 4: Remove `onArtifactsReady` from hook options**

Remove `UseBackendChatStreamOptions` interface and the `onArtifactsReady` destructuring.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/chat/hooks/useBackendChatStream.ts
git commit -m "feat: handle file_event SSE, remove liveFiles and artifacts_ready"
```

---

### Task 8: Frontend — simplify `ArtifactPanel` and `ArtifactsDrawer`

**Files:**
- Modify: `frontend/app/chat/components/ArtifactPanel.tsx` (rewrite to use `fileTree` + `liveReadFile` only)
- Modify: `frontend/app/chat/components/ArtifactsDrawer.tsx` (simplify props, remove run selector)
- Modify: `frontend/app/chat/ChatInterface.tsx` (update props, remove `artifactRunId`/`liveFiles`/`onArtifactsReady`)

- [ ] **Step 1: Rewrite `ArtifactPanel` props and logic**

New props:
```typescript
interface ArtifactPanelProps {
  threadId: string
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
  className?: string
}
```

Replace `fileInfoToNode`, `liveFilesToNodes`, and dual-mode logic with:
```typescript
function fileTreeToNodes(
  tree: Record<string, { action: string; size?: number; timestamp?: number }>
): FileNode[] {
  return Object.entries(tree).map(([path, info]) => {
    const name = path.split('/').pop() ?? path
    const ext = name.includes('.') ? (name.split('.').pop() ?? '') : ''
    return { name, path, type: 'file' as const, extension: ext }
  })
}
```

File selection always uses `artifactService.liveReadFile(threadId, path)`.

Remove: `runId` prop, `isLiveMode`, `artifactService.listRunFiles`, `artifactService.downloadFile`, `fileInfoToNode`, `LiveFileEntry` export.

- [ ] **Step 2: Simplify `ArtifactsDrawer`**

New props:
```typescript
interface ArtifactsDrawerProps {
  isOpen: boolean
  onClose: () => void
  threadId: string
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
}
```

Remove: `runId` prop, `liveFiles` prop, run list loading (`artifactService.listRuns`), run selector dropdown.

Pass `fileTree` directly to `ArtifactPanel`.

- [ ] **Step 3: Update `ChatInterface.tsx`**

Replace:
```typescript
const [artifactRunId, setArtifactRunId] = useState<string | null>(null)

const liveFiles = useMemo(() => {
  const streamingMsg = messages.find(m => m.role === 'assistant' && m.isStreaming)
  return (streamingMsg?.metadata?.liveFiles as ...) ?? []
}, [messages])
```

With:
```typescript
const fileTree = useMemo(() => {
  // Find the latest message with fileTree (streaming or completed)
  for (let i = messages.length - 1; i >= 0; i--) {
    const ft = messages[i].metadata?.fileTree as Record<string, any> | undefined
    if (ft && Object.keys(ft).length > 0) return ft
  }
  return undefined
}, [messages])
```

Update auto-open logic to use `fileTree`:
```typescript
const hasFiles = fileTree && Object.keys(fileTree).length > 0
```

Update `ArtifactsDrawer` usage:
```tsx
<ArtifactsDrawer
  isOpen={artifactDrawerOpen}
  onClose={() => setArtifactDrawerOpen(false)}
  threadId={localChatId}
  fileTree={fileTree}
/>
```

Remove `onArtifactsReady` from `useBackendChatStream` options.

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 5: Commit**

```bash
git add frontend/app/chat/components/ArtifactPanel.tsx frontend/app/chat/components/ArtifactsDrawer.tsx frontend/app/chat/ChatInterface.tsx
git commit -m "refactor: simplify ArtifactPanel to use fileTree from file_event SSE"
```

---

### Task 9: End-to-end verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -x -q --timeout=60`
Expected: All tests pass

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Manual E2E test**

1. Start backend and frontend
2. Send a chat message that triggers file creation (e.g., "Create a hello world Python script")
3. Verify: ArtifactPanel opens automatically when first `file_event` arrives
4. Verify: File tree shows the created file in real-time
5. Verify: Clicking a file shows its content via live read
6. Verify: Subsequent edits update the file tree

- [ ] **Step 4: Final commit with any fixes**

```bash
git add -A && git commit -m "fix: e2e verification fixes for file preview refactor"
```
