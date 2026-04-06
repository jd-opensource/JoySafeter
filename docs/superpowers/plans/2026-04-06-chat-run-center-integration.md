# Chat Run Center Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate all Chat conversations into Run Center so every chat turn is a trackable, persist-on-disconnect run.

**Architecture:** Extend the existing `extension` mechanism used by skill_creator. Frontend creates a run via `POST /v1/runs` before sending the WS frame, passes `run_id` via `extension: { kind: "chat" }`. Backend mirrors all stream events to durable storage. Chat agent registered alongside skill_creator in the agent registry.

**Tech Stack:** Python/FastAPI (backend), React/Next.js + TanStack Query (frontend), PostgreSQL, Redis pub/sub, WebSocket

**Spec:** `docs/superpowers/specs/2026-04-06-chat-run-center-integration-design.md`

---

## File Structure

### New files
| File | Purpose |
|---|---|
| `backend/app/services/run_reducers/chat.py` | Chat agent definition, reducer, initial projection |
| `backend/tests/test_services/test_chat_run_reducer.py` | Unit tests for chat reducer |
| `backend/tests/test_api/test_chat_protocol_chat_extension.py` | Tests for new `chat` extension kind |
| `backend/tests/test_api/test_chat_commands_chat_run.py` | Tests for `ChatRunTurnCommand` routing |

### Modified files
| File | Change |
|---|---|
| `backend/app/services/run_reducers/__init__.py` | Register chat agent |
| `backend/app/websocket/chat_protocol.py` | Accept `extension.kind = "chat"`, add `ParsedChatExtension` |
| `backend/app/websocket/chat_commands.py` | Add `ChatRunTurnCommand`, update union + routing |
| `backend/app/websocket/chat_turn_executor.py` | Handle `ChatRunTurnCommand` in `prepare_standard_turn` |
| `backend/app/websocket/chat_ws_handler.py` | Generalize "Skill Creator run failed" error message |
| `backend/app/api/v1/runs.py` | Make `graph_id` optional on `GET /v1/runs/active` |
| `backend/app/services/run_service.py` | Make `graph_id` optional in `find_latest_active_run` |
| `backend/app/repositories/agent_run.py` | Make `graph_id` optional in repository query |
| `frontend/lib/ws/chat/types.ts` | Add `ChatExtension` type, generalize extension union |
| `frontend/lib/ws/chat/chatWsClient.ts` | Generalize `serializeExtension` for chat extension |
| `frontend/app/chat/hooks/useChatWebSocket.ts` | Create run before WS frame, pass extension |
| `frontend/app/chat/ChatProvider.tsx` | Add `runId` to stream context |
| `frontend/lib/utils/runHelpers.ts` | Add `"chat"` case to `buildRunHref` |
| `frontend/services/runService.ts` | Add `findActiveChatRun` convenience method |
| `frontend/app/runs/[runId]/page.tsx` | Add Chat-specific Overview tab content |

---

### Task 1: Chat Run Reducer + Agent Registration

**Files:**
- Create: `backend/app/services/run_reducers/chat.py`
- Modify: `backend/app/services/run_reducers/__init__.py`
- Test: `backend/tests/test_services/test_chat_run_reducer.py`

- [ ] **Step 1: Write failing tests for chat reducer**

Create `backend/tests/test_services/test_chat_run_reducer.py`:

```python
from app.services.agent_registry import agent_registry


def test_chat_definition_registered() -> None:
    definition = agent_registry.get("chat")
    assert definition.agent_name == "chat"
    assert definition.display_name == "Chat"
    assert definition.run_type == "chat_turn"


def test_chat_initial_projection() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection(
        {"graph_id": "g-1", "thread_id": "t-1"},
        status="queued",
    )
    assert projection["run_type"] == "chat_turn"
    assert projection["status"] == "queued"
    assert projection["graph_id"] == "g-1"
    assert projection["thread_id"] == "t-1"
    assert projection["user_message"] is None
    assert projection["assistant_message"] is None
    assert projection["file_tree"] == {}
    assert projection["preview_data"] is None
    assert projection["node_execution_log"] == []
    assert projection["interrupt"] is None


def test_chat_reducer_user_message_added() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="user_message_added",
        payload={"message": {"content": "hello", "files": []}},
        status="running",
    )
    assert result["user_message"] == {"content": "hello", "files": []}


def test_chat_reducer_assistant_message_started() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="assistant_message_started",
        payload={"message": {"id": "msg-1", "content": "", "tool_calls": []}},
        status="running",
    )
    assert result["assistant_message"]["id"] == "msg-1"
    assert result["assistant_message"]["content"] == ""


def test_chat_reducer_content_delta() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    projection["assistant_message"] = {"id": "msg-1", "content": "hel", "tool_calls": []}
    result = definition.reducer(
        projection,
        event_type="content_delta",
        payload={"message_id": "msg-1", "delta": "lo"},
        status="running",
    )
    assert result["assistant_message"]["content"] == "hello"


def test_chat_reducer_tool_start() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    projection["assistant_message"] = {"id": "msg-1", "content": "", "tool_calls": []}
    result = definition.reducer(
        projection,
        event_type="tool_start",
        payload={
            "message_id": "msg-1",
            "tool": {"id": "t-1", "name": "search", "args": {}, "status": "running"},
        },
        status="running",
    )
    assert len(result["assistant_message"]["tool_calls"]) == 1
    assert result["assistant_message"]["tool_calls"][0]["name"] == "search"


def test_chat_reducer_tool_end_updates_tool_and_captures_preview() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    projection["assistant_message"] = {
        "id": "msg-1",
        "content": "",
        "tool_calls": [{"id": "t-1", "name": "preview_skill", "args": {}, "status": "running"}],
    }
    result = definition.reducer(
        projection,
        event_type="tool_end",
        payload={
            "message_id": "msg-1",
            "tool_id": "t-1",
            "tool_name": "preview_skill",
            "tool_output": {"html": "<p>preview</p>"},
        },
        status="running",
    )
    assert result["assistant_message"]["tool_calls"][0]["status"] == "completed"
    assert result["preview_data"] == {"html": "<p>preview</p>"}


def test_chat_reducer_file_event_create_and_delete() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="file_event",
        payload={"path": "/tmp/a.txt", "action": "create", "size": 100},
        status="running",
    )
    assert "/tmp/a.txt" in result["file_tree"]
    result2 = definition.reducer(
        result,
        event_type="file_event",
        payload={"path": "/tmp/a.txt", "action": "delete"},
        status="running",
    )
    assert "/tmp/a.txt" not in result2["file_tree"]


def test_chat_reducer_node_start_and_end() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="node_start",
        payload={"node_name": "agent", "timestamp": 1000},
        status="running",
    )
    assert len(result["node_execution_log"]) == 1
    assert result["node_execution_log"][0]["node_name"] == "agent"
    assert result["node_execution_log"][0]["status"] == "running"
    result2 = definition.reducer(
        result,
        event_type="node_end",
        payload={"node_name": "agent", "timestamp": 2000},
        status="running",
    )
    assert result2["node_execution_log"][0]["status"] == "completed"


def test_chat_reducer_interrupt() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="interrupt",
        payload={"interrupt": {"type": "human_review", "data": {}}},
        status="interrupt_wait",
    )
    assert result["interrupt"] == {"type": "human_review", "data": {}}


def test_chat_reducer_error() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="error",
        payload={"message": "something broke"},
        status="failed",
    )
    assert result["meta"]["error"] == "something broke"


def test_chat_reducer_done() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="done",
        payload={},
        status="completed",
    )
    assert result["meta"]["completed"] is True
    assert result["status"] == "completed"


def test_chat_reducer_status_message() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")
    result = definition.reducer(
        projection,
        event_type="status",
        payload={"message": "Thinking..."},
        status="running",
    )
    assert result["meta"]["status_message"] == "Thinking..."


def test_chat_reducer_run_initialized() -> None:
    definition = agent_registry.get("chat")
    result = definition.reducer(
        None,
        event_type="run_initialized",
        payload={"graph_id": "g-1", "thread_id": "t-1"},
        status="queued",
    )
    assert result["graph_id"] == "g-1"
    assert result["thread_id"] == "t-1"
    assert result["status"] == "queued"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_services/test_chat_run_reducer.py -v`
Expected: FAIL — `KeyError: 'Unknown agent definition: chat'`

- [ ] **Step 3: Implement the chat reducer**

Create `backend/app/services/run_reducers/chat.py`:

```python
"""
Chat run projection reducer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return {
        "version": 1,
        "run_type": "chat_turn",
        "status": "queued",
        "graph_id": None,
        "thread_id": None,
        "user_message": None,
        "assistant_message": None,
        "file_tree": {},
        "preview_data": None,
        "node_execution_log": [],
        "interrupt": None,
        "meta": {},
    }


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["graph_id"] = payload.get("graph_id")
    projection["thread_id"] = payload.get("thread_id")
    return projection


def apply_chat_event(
    projection: dict[str, Any] | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    next_proj = _deepcopy_projection(projection)
    next_proj["status"] = status

    if event_type == "run_initialized":
        return make_initial_projection(
            {"graph_id": payload.get("graph_id"), "thread_id": payload.get("thread_id")},
            status,
        )

    if event_type == "user_message_added":
        message = payload.get("message")
        if isinstance(message, dict):
            next_proj["user_message"] = message
        return next_proj

    if event_type == "assistant_message_started":
        message = payload.get("message")
        if isinstance(message, dict):
            next_proj["assistant_message"] = message
        return next_proj

    if event_type == "content_delta":
        msg = next_proj.get("assistant_message")
        if msg and payload.get("message_id") == msg.get("id"):
            msg["content"] = f"{msg.get('content', '')}{payload.get('delta', '')}"
        return next_proj

    if event_type == "tool_start":
        msg = next_proj.get("assistant_message")
        tool = payload.get("tool")
        if msg and isinstance(tool, dict) and payload.get("message_id") == msg.get("id"):
            msg.setdefault("tool_calls", []).append(tool)
        return next_proj

    if event_type == "tool_end":
        msg = next_proj.get("assistant_message")
        tool_id = payload.get("tool_id")
        tool_name = payload.get("tool_name")
        tool_output = payload.get("tool_output")
        end_time = payload.get("end_time")
        if msg and payload.get("message_id") == msg.get("id"):
            for tool in msg.get("tool_calls", []):
                if tool_id and tool.get("id") != tool_id:
                    continue
                if not tool_id and tool.get("status") != "running":
                    continue
                tool["status"] = "completed"
                tool["result"] = tool_output
                if end_time is not None:
                    tool["endTime"] = end_time
                break
        if tool_name == "preview_skill" and tool_output is not None:
            next_proj["preview_data"] = tool_output
        return next_proj

    if event_type == "file_event":
        path = payload.get("path")
        action = payload.get("action")
        if not path or not action:
            return next_proj
        if action == "delete":
            next_proj["file_tree"].pop(path, None)
        else:
            next_proj["file_tree"][path] = {
                "action": action,
                "size": payload.get("size"),
                "timestamp": payload.get("timestamp"),
            }
        return next_proj

    if event_type == "node_start":
        next_proj["node_execution_log"].append({
            "node_name": payload.get("node_name"),
            "status": "running",
            "start_time": payload.get("timestamp"),
            "end_time": None,
        })
        return next_proj

    if event_type == "node_end":
        node_name = payload.get("node_name")
        for entry in reversed(next_proj["node_execution_log"]):
            if entry.get("node_name") == node_name and entry.get("status") == "running":
                entry["status"] = "completed"
                entry["end_time"] = payload.get("timestamp")
                break
        return next_proj

    if event_type == "interrupt":
        next_proj["interrupt"] = payload.get("interrupt")
        return next_proj

    if event_type == "error":
        next_proj["meta"]["error"] = payload.get("message")
        return next_proj

    if event_type == "done":
        next_proj["meta"]["completed"] = True
        return next_proj

    if event_type == "status":
        next_proj["meta"]["status_message"] = payload.get("message")
        return next_proj

    return next_proj
```

- [ ] **Step 4: Register in `__init__.py`**

Modify `backend/app/services/run_reducers/__init__.py` — add after the skill_creator registration:

```python
from .chat import apply_chat_event, make_initial_projection as chat_make_initial_projection

agent_registry.register(
    AgentDefinition(
        agent_name="chat",
        display_name="Chat",
        run_type="chat_turn",
        reducer=apply_chat_event,
        make_initial_projection=chat_make_initial_projection,
    )
)
```

Update `__all__` to include the new exports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_services/test_chat_run_reducer.py -v`
Expected: All 14 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/run_reducers/chat.py \
        backend/app/services/run_reducers/__init__.py \
        backend/tests/test_services/test_chat_run_reducer.py
git commit -m "feat: add chat run reducer and agent registration"
```

---

### Task 2: Chat Protocol Extension + Command Routing

**Files:**
- Modify: `backend/app/websocket/chat_protocol.py`
- Modify: `backend/app/websocket/chat_commands.py`
- Test: `backend/tests/test_api/test_chat_protocol_chat_extension.py`
- Test: `backend/tests/test_api/test_chat_commands_chat_run.py`

- [ ] **Step 1: Write failing tests for chat extension parsing**

Create `backend/tests/test_api/test_chat_protocol_chat_extension.py`:

```python
from app.websocket.chat_protocol import (
    ParsedChatStartFrame,
    parse_client_frame,
)


def test_parse_chat_extension_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-chat-1",
            "thread_id": "t-1",
            "graph_id": None,
            "input": {"message": "hello"},
            "extension": {"kind": "chat", "run_id": "run-abc"},
            "metadata": {},
        }
    )
    assert isinstance(parsed, ParsedChatStartFrame)
    assert parsed.extension is not None
    assert parsed.extension.kind == "chat"
    assert parsed.extension.run_id == "run-abc"


def test_parse_chat_extension_with_no_run_id():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-chat-2",
            "input": {"message": "hi"},
            "extension": {"kind": "chat"},
            "metadata": {},
        }
    )
    assert parsed.extension is not None
    assert parsed.extension.kind == "chat"
    assert parsed.extension.run_id is None


def test_unsupported_extension_kind_still_rejected():
    import pytest
    from app.websocket.chat_protocol import ChatProtocolError

    with pytest.raises(ChatProtocolError, match="unsupported extension kind"):
        parse_client_frame(
            {
                "type": "chat.start",
                "request_id": "req-bad",
                "input": {"message": "hi"},
                "extension": {"kind": "copilot"},
                "metadata": {},
            }
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api/test_chat_protocol_chat_extension.py -v`
Expected: FAIL — `ChatProtocolError: unsupported extension kind: chat`

- [ ] **Step 3: Add `ParsedChatExtension` and update `_parse_extension`**

In `backend/app/websocket/chat_protocol.py`:

Add new dataclass after `ParsedSkillCreatorExtension`:

```python
@dataclass(frozen=True)
class ParsedChatExtension:
    """Extension payload for Chat run turns."""
    kind: Literal["chat"]
    run_id: str | None
```

Update `ParsedChatStartFrame.extension` type annotation:

```python
extension: ParsedSkillCreatorExtension | ParsedChatExtension | None
```

Replace `_parse_extension` body to handle both kinds:

```python
def _parse_extension(raw_extension: Any, request_id: str) -> ParsedSkillCreatorExtension | ParsedChatExtension | None:
    if raw_extension is None:
        return None
    if not isinstance(raw_extension, dict):
        raise ChatProtocolError("extension must be an object", request_id=request_id)

    kind = raw_extension.get("kind")
    run_id = _coerce_request_id(raw_extension.get("run_id"))

    if kind == "skill_creator":
        edit_skill_id = _coerce_request_id(raw_extension.get("edit_skill_id"))
        return ParsedSkillCreatorExtension(kind="skill_creator", run_id=run_id, edit_skill_id=edit_skill_id)

    if kind == "chat":
        return ParsedChatExtension(kind="chat", run_id=run_id)

    raise ChatProtocolError(
        f"unsupported extension kind: {kind or '<missing>'}",
        request_id=request_id,
    )
```

- [ ] **Step 4: Run protocol tests**

Run: `cd backend && python -m pytest tests/test_api/test_chat_protocol_chat_extension.py tests/test_api/test_chat_protocol.py -v`
Expected: All PASS (new + existing tests)

- [ ] **Step 5: Write failing tests for ChatRunTurnCommand**

Create `backend/tests/test_api/test_chat_commands_chat_run.py`:

```python
from app.websocket.chat_commands import ChatRunTurnCommand, build_command_from_parsed_frame
from app.websocket.chat_protocol import parse_client_frame


def test_chat_extension_produces_chat_run_turn_command():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-1",
            "thread_id": "t-1",
            "input": {"message": "hello"},
            "extension": {"kind": "chat", "run_id": "run-xyz"},
            "metadata": {},
        }
    )
    command = build_command_from_parsed_frame(parsed)
    assert isinstance(command, ChatRunTurnCommand)
    assert command.run_id == "run-xyz"
    assert command.message == "hello"


def test_no_extension_still_produces_standard_command():
    from app.websocket.chat_commands import StandardChatTurnCommand

    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-2",
            "input": {"message": "hi"},
            "extension": None,
            "metadata": {},
        }
    )
    command = build_command_from_parsed_frame(parsed)
    assert isinstance(command, StandardChatTurnCommand)
    assert not isinstance(command, ChatRunTurnCommand)
```

- [ ] **Step 6: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_api/test_chat_commands_chat_run.py -v`
Expected: FAIL — `ChatRunTurnCommand` not defined

- [ ] **Step 7: Add `ChatRunTurnCommand` and update routing**

In `backend/app/websocket/chat_commands.py`:

Add import:
```python
from app.websocket.chat_protocol import ParsedChatExtension, ParsedChatStartFrame
```

Add new command class after `SkillCreatorTurnCommand`:

```python
@dataclass(frozen=True)
class ChatRunTurnCommand(StandardChatTurnCommand):
    """Command for a Chat run turn, extending the standard command."""
    run_id: str | None = None
```

Update union type:

```python
ChatTurnCommand = StandardChatTurnCommand | SkillCreatorTurnCommand | ChatRunTurnCommand
```

Update `build_command_from_parsed_frame` — replace the entire body after `_sanitize_metadata_files` with properly ordered `isinstance` checks. The **critical ordering** is: check `None` → check `ParsedChatExtension` → check `ParsedSkillCreatorExtension`. The chat branch MUST come before any `extension.edit_skill_id` access (line 53 of current code), otherwise `ParsedChatExtension` (which has no `edit_skill_id` attribute) will cause `AttributeError`.

```python
def build_command_from_parsed_frame(frame: ParsedChatStartFrame) -> ChatTurnCommand:
    """Convert a validated ParsedChatStartFrame into a ChatTurnCommand."""
    metadata, files = _sanitize_metadata_files(frame.metadata, frame.input.files)
    model = frame.input.model

    extension = frame.extension
    if extension is None:
        return StandardChatTurnCommand(
            request_id=frame.request_id,
            message=frame.input.message,
            thread_id=frame.thread_id,
            graph_id=frame.graph_id,
            model=model,
            metadata=metadata,
            files=files,
        )

    if isinstance(extension, ParsedChatExtension):
        return ChatRunTurnCommand(
            request_id=frame.request_id,
            message=frame.input.message,
            thread_id=frame.thread_id,
            graph_id=frame.graph_id,
            model=model,
            metadata=metadata,
            files=files,
            run_id=extension.run_id,
        )

    # skill_creator path
    if extension.edit_skill_id:
        metadata["edit_skill_id"] = extension.edit_skill_id

    return SkillCreatorTurnCommand(
        request_id=frame.request_id,
        message=frame.input.message,
        thread_id=frame.thread_id,
        graph_id=frame.graph_id,
        model=model,
        metadata=metadata,
        files=files,
        run_id=extension.run_id,
        edit_skill_id=extension.edit_skill_id,
    )
```

- [ ] **Step 8: Run all command tests**

Run: `cd backend && python -m pytest tests/test_api/test_chat_commands_chat_run.py tests/test_api/test_chat_protocol_chat_extension.py tests/test_api/test_chat_protocol.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/websocket/chat_protocol.py \
        backend/app/websocket/chat_commands.py \
        backend/tests/test_api/test_chat_protocol_chat_extension.py \
        backend/tests/test_api/test_chat_commands_chat_run.py
git commit -m "feat: add chat extension kind and ChatRunTurnCommand"
```

---

### Task 3: Backend Executor + Handler — Persist Chat Runs

**Files:**
- Modify: `backend/app/websocket/chat_turn_executor.py:66-91`
- Modify: `backend/app/websocket/chat_ws_handler.py:507-512`

- [ ] **Step 1: Update `prepare_standard_turn` to handle `ChatRunTurnCommand`**

In `backend/app/websocket/chat_turn_executor.py`, import the new command:

```python
from app.websocket.chat_commands import ChatTurnCommand, ChatRunTurnCommand, SkillCreatorTurnCommand
```

In `prepare_standard_turn`, after the `SkillCreatorTurnCommand` branch (line 74-78), add:

```python
        elif isinstance(command, ChatRunTurnCommand):
            run_id = self._parse_uuid(command.run_id)
            persist_on_disconnect = run_id is not None
```

This means `ChatRunTurnCommand` gets the same `persist_on_disconnect` and `run_id` behavior as `SkillCreatorTurnCommand`. The rest of the execution path (heartbeat, event mirroring, finalization) is driven by `task_entry.run_id` and `task_entry.persist_on_disconnect`, which are set from `PreparedStandardTurn`.

- [ ] **Step 2: Wire resume turns to persist under the same `run_id`**

Per spec Section 2.4, resume turns (`chat.resume` frames) must also be persisted under the same `run_id` from the original turn. 

In `backend/app/websocket/chat_ws_handler.py`, the `_handle_resume` method (around line 208) creates a task via `_task_supervisor.create_task(...)`. Currently, resume tasks do **not** set `persist_on_disconnect` or `run_id`. 

Update `_handle_resume` — before calling `_task_supervisor.create_task`, look up the existing task entry for the thread to get the `run_id`:

```python
        # Inherit run_id from the previous task entry for this thread (if persisted)
        existing_entry = self._task_supervisor.get_by_thread(thread_id)
        resume_run_id = existing_entry.run_id if existing_entry else None
        resume_persist = existing_entry.persist_on_disconnect if existing_entry else False

        self._task_supervisor.create_task(
            request_id,
            runner(),
            name=f"chat-ws-resume:{request_id}",
            thread_id=thread_id,
            run_id=resume_run_id,
            persist_on_disconnect=resume_persist,
        )
```

Also verify `ChatTaskSupervisor.create_task` accepts `run_id` and `persist_on_disconnect` kwargs (it does for standard turns — check the `ChatTaskEntry` creation path). If `create_task` doesn't pass these through, update it to do so.

In `backend/app/websocket/chat_turn_executor.py`, `execute_resume_turn` (or `run_resume_turn`) must also read `task_entry.run_id` and `task_entry.persist_on_disconnect` from the supervisor to set `tolerate_disconnect` and `agent_run_id`, the same way `execute_standard_turn` does at lines 121-123:

```python
        task_entry = handler._task_supervisor.get(request_id)
        agent_run_id = task_entry.run_id if task_entry else None
        tolerate_disconnect = bool(task_entry and task_entry.persist_on_disconnect)
```

This ensures the resume turn mirrors events to the durable run log and survives WS disconnects.

- [ ] **Step 3: Generalize error message in `_finalize_task`**

In `backend/app/websocket/chat_ws_handler.py`, find line 512:

```python
                    error_message="Skill Creator run failed",
```

Replace with:

```python
                    error_message="Agent run failed",
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/test_api/test_chat_protocol.py tests/test_services/test_run_reducers.py tests/test_api/test_runs_api.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/websocket/chat_turn_executor.py \
        backend/app/websocket/chat_ws_handler.py
git commit -m "feat: persist chat runs — executor handles ChatRunTurnCommand"
```

---

### Task 4: Make `graph_id` Optional on Active Run Endpoint

**Files:**
- Modify: `backend/app/api/v1/runs.py:107`
- Modify: `backend/app/services/run_service.py:286-310`
- Modify: `backend/app/repositories/agent_run.py:72-90`

- [ ] **Step 1: Update repository — make `graph_id` optional**

In `backend/app/repositories/agent_run.py`, method `find_latest_active_run` (line 72):

Change signature from:
```python
    async def find_latest_active_run(
        self,
        *,
        user_id: str,
        agent_name: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
```

To:
```python
    async def find_latest_active_run(
        self,
        *,
        user_id: str,
        agent_name: str,
        graph_id: Optional[uuid.UUID] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
```

Update query body — make `graph_id` filter conditional (line 81-85):

```python
        active_statuses = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.INTERRUPT_WAIT)
        query = select(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.agent_name == agent_name,
            AgentRun.status.in_(active_statuses),
        )
        if graph_id is not None:
            query = query.where(AgentRun.graph_id == graph_id)
        if thread_id:
            query = query.where(AgentRun.thread_id == thread_id)
```

- [ ] **Step 2: Update service layer**

In `backend/app/services/run_service.py`, method `find_latest_active_run` (line 286):

Change `graph_id: uuid.UUID` to `graph_id: Optional[uuid.UUID] = None` in the signature.

- [ ] **Step 3: Update API endpoint**

In `backend/app/api/v1/runs.py`, endpoint `get_active_run` (line 107):

Change:
```python
    graph_id: uuid.UUID = Query(...),
```
To:
```python
    graph_id: uuid.UUID | None = Query(None),
```

- [ ] **Step 4: Run existing tests**

Run: `cd backend && python -m pytest tests/test_api/test_runs_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/runs.py \
        backend/app/services/run_service.py \
        backend/app/repositories/agent_run.py
git commit -m "feat: make graph_id optional on GET /v1/runs/active"
```

---

### Task 5: Frontend — Chat Extension Types + WS Client

**Files:**
- Modify: `frontend/lib/ws/chat/types.ts`
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`

- [ ] **Step 1: Add `ChatExtension` type**

In `frontend/lib/ws/chat/types.ts`, after `SkillCreatorExtension` (line 46):

```typescript
export interface ChatExtension {
  kind: 'chat'
  runId?: string | null
}
```

Update `ChatSendParams.extension` type (line 53):

```typescript
  extension?: SkillCreatorExtension | ChatExtension | null
```

- [ ] **Step 2: Generalize `serializeExtension`**

In `frontend/lib/ws/chat/chatWsClient.ts`, update the import to include `ChatExtension`:

```typescript
import type {
  ChatExtension,
  ChatResumeParams,
  ChatSendParams,
  ChatTerminalResult,
  ChatWsClient,
  ConnectionState,
  IncomingChatAcceptedEvent,
  IncomingChatWsEvent,
  SkillCreatorExtension,
} from './types'
```

Replace `serializeExtension` function (line 406-416):

```typescript
function serializeExtension(extension?: SkillCreatorExtension | ChatExtension | null): Record<string, unknown> | null {
  if (!extension) {
    return null
  }

  if (extension.kind === 'skill_creator') {
    return {
      kind: extension.kind,
      run_id: (extension as SkillCreatorExtension).runId ?? null,
      edit_skill_id: (extension as SkillCreatorExtension).editSkillId ?? null,
    }
  }

  if (extension.kind === 'chat') {
    return {
      kind: extension.kind,
      run_id: (extension as ChatExtension).runId ?? null,
    }
  }

  return null
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/ws/chat/types.ts \
        frontend/lib/ws/chat/chatWsClient.ts
git commit -m "feat: add ChatExtension type and generalize WS serialization"
```

---

### Task 6: Frontend — Chat Send Flow Creates Run

**Files:**
- Modify: `frontend/app/chat/hooks/useChatWebSocket.ts`
- Modify: `frontend/app/chat/ChatProvider.tsx`
- Modify: `frontend/services/runService.ts`

- [ ] **Step 1: Add `findActiveChatRun` to runService**

In `frontend/services/runService.ts`, after `findActiveSkillCreatorRun` (line 152):

```typescript
  async findActiveChatRun(params: { threadId: string }): Promise<RunSummary | null> {
    return this.findActiveRun({
      agentName: 'chat',
      threadId: params.threadId,
    })
  },
```

Also update `findActiveRun` to handle optional `graphId` — change the params construction (line 138-142):

```typescript
  async findActiveRun(params: {
    agentName: string
    graphId?: string | null
    threadId?: string | null
  }): Promise<RunSummary | null> {
    const query = new URLSearchParams({
      agent_name: params.agentName,
    })
    if (params.graphId) query.set('graph_id', params.graphId)
    if (params.threadId) query.set('thread_id', params.threadId)
    return apiGet<RunSummary | null>(`${API_ENDPOINTS.runs}/active?${query.toString()}`)
  },
```

- [ ] **Step 2: Update `useChatWebSocket` to create a run before sending**

In `frontend/app/chat/hooks/useChatWebSocket.ts`, add import at top:

```typescript
import { runService } from '@/services/runService'
import type { ChatExtension } from '@/lib/ws/chat/types'
```

In the `sendMessage` callback, before the `chatWs.sendChat(...)` call, add run creation logic. The `graphId` and `threadId` are available from the `sendMessage` function parameters (passed via opts from the session context), NOT from refs:

```typescript
// Inside sendMessage, after building requestId and before chatWs.sendChat:
// graphId and threadId come from the sendMessage opts/params, not refs
let chatRunId: string | null = null
try {
  if (graphId) {
    const runResponse = await runService.createRun({
      agent_name: 'chat',
      graph_id: graphId,
      message: input.message,
      thread_id: threadId || undefined,
    })
    chatRunId = runResponse.run_id
  }
} catch (err) {
  console.warn('[Chat] Failed to create chat run, proceeding without persistence', err)
}
```

Then pass the extension in the `sendChat` params:

```typescript
const extension: ChatExtension | undefined = chatRunId
  ? { kind: 'chat', runId: chatRunId }
  : undefined

await chatWs.sendChat({
  requestId,
  threadId,
  graphId,
  input,
  extension,
  metadata,
  // ... existing onEvent and onAccepted callbacks
})
```

- [ ] **Step 3: Add `runId` to ChatStreamContext**

In `frontend/app/chat/ChatProvider.tsx`, add `runId` state to the stream context:

In the `ChatStreamContextValue` interface (or wherever the stream context shape is defined), add:

```typescript
runId: string | null
```

Wire it from the `useChatWebSocket` hook (the hook should track the latest `chatRunId` in a ref and expose it). The simplest approach: add a `runIdRef` in the hook and expose `runId` via the return value.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/chat/hooks/useChatWebSocket.ts \
        frontend/app/chat/ChatProvider.tsx \
        frontend/services/runService.ts
git commit -m "feat: chat send flow creates run and passes extension"
```

---

### Task 7: Frontend — Run Center UI Updates

**Files:**
- Modify: `frontend/lib/utils/runHelpers.ts:53-59`
- Modify: `frontend/app/runs/[runId]/page.tsx`

- [ ] **Step 1: Update `buildRunHref` for chat runs**

In `frontend/lib/utils/runHelpers.ts`, replace the `buildRunHref` function body (lines 53-59):

```typescript
export function buildRunHref(run: { run_id: string; run_type?: string; agent_name?: string | null }): string {
  if (run.agent_name === 'skill_creator' || run.run_type === 'skill_creator') {
    return `/skills/creator?run=${encodeURIComponent(run.run_id)}`
  }
  if (run.agent_name === 'chat' || run.run_type === 'chat_turn') {
    return `/runs/${encodeURIComponent(run.run_id)}`
  }
  return '#'
}
```

- [ ] **Step 2: Add Chat Overview tab to Run Detail page**

In `frontend/app/runs/[runId]/page.tsx`, the Overview tab currently shows generic run metadata. Add Chat-specific rendering when `agent_name === 'chat'`:

Within the Overview `TabsContent`, add a conditional section:

```tsx
{projection?.run_type === 'chat_turn' && (
  <div className="space-y-4">
    {/* User message */}
    {projection.user_message && (
      <Card className="p-4">
        <h4 className="text-sm font-medium text-muted-foreground mb-2">
          {t('runs.userMessage', 'User Message')}
        </h4>
        <p className="text-sm whitespace-pre-wrap">{projection.user_message.content}</p>
      </Card>
    )}

    {/* Assistant message */}
    {projection.assistant_message && (
      <Card className="p-4">
        <h4 className="text-sm font-medium text-muted-foreground mb-2">
          {t('runs.assistantMessage', 'Assistant Response')}
        </h4>
        <p className="text-sm whitespace-pre-wrap">{projection.assistant_message.content}</p>

        {/* Tool calls */}
        {projection.assistant_message.tool_calls?.length > 0 && (
          <div className="mt-3 space-y-2">
            <h5 className="text-xs font-medium text-muted-foreground">
              {t('runs.toolCalls', 'Tool Calls')}
            </h5>
            {projection.assistant_message.tool_calls.map((tool: any, i: number) => (
              <details key={tool.id || i} className="text-xs border rounded p-2">
                <summary className="cursor-pointer font-medium">
                  {tool.name} — {tool.status}
                </summary>
                {tool.args && (
                  <pre className="mt-1 text-muted-foreground overflow-x-auto">
                    {JSON.stringify(tool.args, null, 2)}
                  </pre>
                )}
                {tool.result && (
                  <pre className="mt-1 text-muted-foreground overflow-x-auto">
                    {JSON.stringify(tool.result, null, 2)}
                  </pre>
                )}
              </details>
            ))}
          </div>
        )}
      </Card>
    )}

    {/* File tree */}
    {projection.file_tree && Object.keys(projection.file_tree).length > 0 && (
      <Card className="p-4">
        <h4 className="text-sm font-medium text-muted-foreground mb-2">
          {t('runs.fileTree', 'Files')}
        </h4>
        <ul className="text-xs space-y-1">
          {Object.entries(projection.file_tree).map(([path, info]: [string, any]) => (
            <li key={path} className="flex items-center gap-2">
              <Badge variant="outline" className="text-[10px]">{info.action}</Badge>
              <span className="font-mono truncate">{path}</span>
            </li>
          ))}
        </ul>
      </Card>
    )}

    {/* Preview data */}
    {projection.preview_data && (
      <Card className="p-4">
        <h4 className="text-sm font-medium text-muted-foreground mb-2">
          {t('runs.previewData', 'Preview')}
        </h4>
        <pre className="text-xs overflow-x-auto">
          {JSON.stringify(projection.preview_data, null, 2)}
        </pre>
      </Card>
    )}

    {/* Node execution log */}
    {projection.node_execution_log?.length > 0 && (
      <Card className="p-4">
        <h4 className="text-sm font-medium text-muted-foreground mb-2">
          {t('runs.nodeLog', 'Execution Log')}
        </h4>
        <ul className="text-xs space-y-1">
          {projection.node_execution_log.map((entry: any, i: number) => (
            <li key={i} className="flex items-center gap-2">
              <Badge variant={entry.status === 'completed' ? 'default' : 'secondary'} className="text-[10px]">
                {entry.status}
              </Badge>
              <span className="font-mono">{entry.node_name}</span>
            </li>
          ))}
        </ul>
      </Card>
    )}
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/utils/runHelpers.ts \
        frontend/app/runs/[runId]/page.tsx
git commit -m "feat: Run Center shows chat runs with overview detail"
```

---

### Task 8: Smoke Test & Final Verification

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python -m pytest tests/test_services/test_chat_run_reducer.py \
    tests/test_services/test_run_reducers.py \
    tests/test_api/test_chat_protocol.py \
    tests/test_api/test_chat_protocol_chat_extension.py \
    tests/test_api/test_chat_commands_chat_run.py \
    tests/test_api/test_runs_api.py -v
```

Expected: All PASS

- [ ] **Step 2: Run frontend type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No type errors

- [ ] **Step 3: Verify `GET /v1/runs/agents` returns Chat**

After starting the backend, call:
```bash
curl -s http://localhost:8000/api/v1/runs/agents -H "Authorization: Bearer <token>" | jq
```

Expected: `items` array includes `{ "agent_name": "chat", "display_name": "Chat" }`

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A && git commit -m "fix: address smoke test findings"
```---
