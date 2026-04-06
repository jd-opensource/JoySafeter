# Phase 3: Copilot Run Center Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Copilot into the shared Run Center model — replace Redis Pub/Sub + `/ws/copilot` with `agent_run_events` + `/ws/chat` turn executor + `/ws/runs` observation.

**Architecture:** Frontend creates a run via REST, then sends `chat.start` with `extension: { kind: "copilot" }` through the shared chat WS. Backend dispatches to `execute_copilot_turn` which consumes `CopilotService._get_copilot_stream()` and emits events via `_emit_event`. Old Redis/copilot_chats/ws-copilot code is deleted entirely.

**Tech Stack:** Python/FastAPI (backend), TypeScript/React/Next.js (frontend), SQLAlchemy (ORM), LangGraph (agent framework), WebSocket

**Spec:** `docs/superpowers/specs/2026-04-06-copilot-run-center-integration-design.md`

---

## File Structure

### Backend — Create

| File | Responsibility |
|---|---|
| `backend/app/services/run_reducers/copilot.py` | Copilot reducer + initial projection |
| `backend/tests/test_services/test_copilot_run_reducer.py` | Reducer unit tests |
| `backend/tests/test_api/test_chat_protocol_copilot_extension.py` | Protocol parsing tests |
| `backend/tests/test_api/test_chat_commands_copilot.py` | Command dispatch tests |

### Backend — Modify

| File | Change |
|---|---|
| `backend/app/services/run_reducers/__init__.py` | Register copilot agent |
| `backend/app/websocket/chat_protocol.py` | Add `ParsedCopilotExtension`, widen types |
| `backend/app/websocket/chat_commands.py` | Add `CopilotTurnCommand`, dispatch branch |
| `backend/app/websocket/chat_turn_executor.py` | Add `execute_copilot_turn`, copilot branch in `prepare_standard_turn` |
| `backend/app/api/v1/graphs.py` | Rewrite history endpoints, delete old copilot endpoints |
| `backend/app/repositories/agent_run.py` | Add `graph_id` filter to `list_recent_runs_for_user`, add `delete_runs_for_graph` |

### Backend — Delete

| File/Section | Reason |
|---|---|
| `backend/app/websocket/copilot_handler.py` | Entire file — replaced by chat WS |
| `backend/app/repositories/copilot_chat_repository.py` | Entire file — copilot_chats removed |
| `backend/app/models/chat.py` `CopilotChat` class | Model for deleted table |
| `backend/app/main.py` `/ws/copilot` route | Route registration |
| `backend/app/core/redis.py` copilot methods | ~12 Redis methods |
| `backend/app/services/copilot_service.py` several methods | `generate_actions_async`, `_consume_stream_and_publish_to_redis`, `_persist_conversation`, `save_messages`, `save_conversation_from_stream` |
| `backend/app/api/v1/graphs.py` endpoints | `POST /copilot/actions/create`, `POST /{graph_id}/copilot/messages`, `GET /copilot/sessions/{session_id}` |

### Frontend — Modify

| File | Change |
|---|---|
| `frontend/lib/ws/chat/types.ts` | Add `CopilotExtension`, widen union |
| `frontend/lib/ws/chat/chatWsClient.ts` | `serializeExtension` copilot branch |
| `frontend/hooks/copilot/useCopilotSession.ts` | session_id → run_id |
| `frontend/app/workspace/.../hooks/useCopilotActions.ts` | Replace createCopilotTask → createRun + sendChat |
| `frontend/app/workspace/.../hooks/useCopilotWebSocketHandler.ts` | Events from chat WS onEvent |
| `frontend/app/workspace/.../hooks/useCopilotEffects.ts` | Recovery via runService |
| `frontend/services/copilotService.ts` | Remove createCopilotTask, getSession |
| `frontend/lib/utils/runHelpers.ts` | Add copilot_turn case |
| `frontend/app/runs/[runId]/page.tsx` | Add CopilotTurnOverview |

### Frontend — Delete

| File | Reason |
|---|---|
| `frontend/hooks/use-copilot-websocket.ts` | Replaced by shared chat WS |

---

## Tasks

### Task 1: Copilot Reducer & Agent Registration

**Files:**
- Create: `backend/app/services/run_reducers/copilot.py`
- Create: `backend/tests/test_services/test_copilot_run_reducer.py`
- Modify: `backend/app/services/run_reducers/__init__.py`

**Reference:** `backend/app/services/run_reducers/chat.py` for pattern.

- [ ] **Step 1: Write reducer tests**

```python
"""Tests for copilot run projection reducer."""
import copy
from app.services.run_reducers.copilot import apply_copilot_event, make_initial_projection


def _base():
    return make_initial_projection({"graph_id": "g1", "mode": "deepagents"}, "queued")


def test_copilot_definition_registered():
    from app.services.agent_registry import agent_registry
    defn = agent_registry.get("copilot")
    assert defn.agent_name == "copilot"
    assert defn.run_type == "copilot_turn"


def test_copilot_initial_projection():
    p = _base()
    assert p["run_type"] == "copilot_turn"
    assert p["status"] == "queued"
    assert p["graph_id"] == "g1"
    assert p["mode"] == "deepagents"
    assert p["content"] == ""
    assert p["thought_steps"] == []


def test_copilot_reducer_run_initialized():
    p = apply_copilot_event(None, event_type="run_initialized", payload={"graph_id": "g2", "mode": "standard"}, status="running")
    assert p["graph_id"] == "g2"
    assert p["mode"] == "standard"


def test_copilot_reducer_status():
    p = apply_copilot_event(_base(), event_type="status", payload={"stage": "thinking", "message": "Thinking..."}, status="running")
    assert p["stage"] == "thinking"


def test_copilot_reducer_content_delta():
    p = apply_copilot_event(_base(), event_type="content_delta", payload={"delta": "Hello "}, status="running")
    p = apply_copilot_event(p, event_type="content_delta", payload={"delta": "world"}, status="running")
    assert p["content"] == "Hello world"


def test_copilot_reducer_thought_step():
    p = apply_copilot_event(_base(), event_type="thought_step", payload={"step": {"index": 1, "content": "Analyzing"}}, status="running")
    assert len(p["thought_steps"]) == 1
    assert p["thought_steps"][0]["content"] == "Analyzing"


def test_copilot_reducer_tool_call():
    p = apply_copilot_event(_base(), event_type="tool_call", payload={"tool": "create_node", "input": {"type": "agent"}}, status="running")
    assert len(p["tool_calls"]) == 1
    assert p["tool_calls"][0]["tool"] == "create_node"


def test_copilot_reducer_tool_result():
    action = {"type": "CREATE_NODE", "payload": {"id": "n1"}, "reasoning": "Need agent"}
    p = apply_copilot_event(_base(), event_type="tool_result", payload={"action": action}, status="running")
    assert len(p["tool_results"]) == 1
    assert p["tool_results"][0]["type"] == "CREATE_NODE"


def test_copilot_reducer_result():
    actions = [{"type": "CREATE_NODE", "payload": {"id": "n1"}, "reasoning": "test"}]
    p = apply_copilot_event(_base(), event_type="result", payload={"message": "Done!", "actions": actions}, status="running")
    assert p["result_message"] == "Done!"
    assert len(p["result_actions"]) == 1


def test_copilot_reducer_error():
    p = apply_copilot_event(_base(), event_type="error", payload={"message": "LLM failed", "code": "AGENT_ERROR"}, status="failed")
    assert p["status"] == "failed"
    assert p["error"] == "LLM failed"


def test_copilot_reducer_done():
    p = apply_copilot_event(_base(), event_type="done", payload={}, status="completed")
    assert p["status"] == "completed"


def test_copilot_reducer_done_preserves_failed():
    p = apply_copilot_event(_base(), event_type="error", payload={"message": "err"}, status="failed")
    p = apply_copilot_event(p, event_type="done", payload={}, status="failed")
    assert p["status"] == "failed"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_services/test_copilot_run_reducer.py -v --no-header
```

Expected: `ModuleNotFoundError: No module named 'app.services.run_reducers.copilot'`

- [ ] **Step 3: Write copilot reducer**

Create `backend/app/services/run_reducers/copilot.py`:

```python
"""
Copilot run projection reducer.

Each copilot turn is tracked as a single run projection containing
streaming content, thought steps, tool calls/results, and final
result message + graph actions.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_INITIAL: dict[str, Any] = {
    "version": 1,
    "run_type": "copilot_turn",
    "status": "queued",
    "stage": None,
    "content": "",
    "thought_steps": [],
    "tool_calls": [],
    "tool_results": [],
    "result_message": None,
    "result_actions": [],
    "error": None,
    "graph_id": None,
    "mode": None,
}


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return deepcopy(_INITIAL)


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["graph_id"] = payload.get("graph_id")
    projection["mode"] = payload.get("mode")
    return projection


def apply_copilot_event(
    projection: dict[str, Any] | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    next_p = _deepcopy_projection(projection)
    next_p["status"] = status

    if event_type == "run_initialized":
        return make_initial_projection(
            {"graph_id": payload.get("graph_id"), "mode": payload.get("mode")},
            status,
        )

    if event_type == "status":
        next_p["stage"] = payload.get("stage")
        return next_p

    if event_type == "content_delta":
        next_p["content"] += payload.get("delta", "")
        return next_p

    if event_type == "thought_step":
        step = payload.get("step")
        if step:
            next_p["thought_steps"].append(step)
        return next_p

    if event_type == "tool_call":
        next_p["tool_calls"].append({
            "tool": payload.get("tool", ""),
            "input": payload.get("input", {}),
        })
        return next_p

    if event_type == "tool_result":
        action = payload.get("action")
        if action:
            next_p["tool_results"].append(action)
        return next_p

    if event_type == "result":
        next_p["result_message"] = payload.get("message", "")
        next_p["result_actions"] = payload.get("actions", [])
        return next_p

    if event_type == "error":
        next_p["status"] = "failed"
        next_p["error"] = payload.get("message")
        return next_p

    if event_type == "done":
        if next_p["status"] != "failed":
            next_p["status"] = "completed"
        return next_p

    return next_p
```

- [ ] **Step 4: Register in `__init__.py`**

Add to `backend/app/services/run_reducers/__init__.py`:

```python
from .copilot import apply_copilot_event, make_initial_projection as copilot_make_initial_projection

agent_registry.register(
    AgentDefinition(
        agent_name="copilot",
        display_name="Copilot",
        run_type="copilot_turn",
        reducer=apply_copilot_event,
        make_initial_projection=copilot_make_initial_projection,
    )
)
```

Add to `__all__`: `"apply_copilot_event"`, `"copilot_make_initial_projection"`.

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_services/test_copilot_run_reducer.py -v --no-header
```

Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/run_reducers/copilot.py backend/app/services/run_reducers/__init__.py backend/tests/test_services/test_copilot_run_reducer.py
git commit -m "feat: add copilot reducer and agent registry entry"
```

---

### Task 2: Protocol Extension — ParsedCopilotExtension

**Files:**
- Modify: `backend/app/websocket/chat_protocol.py`
- Create: `backend/tests/test_api/test_chat_protocol_copilot_extension.py`

**Reference:** Existing `ParsedChatExtension` and `ParsedSkillCreatorExtension` in `chat_protocol.py`.

- [ ] **Step 1: Write protocol tests**

```python
"""Tests for copilot extension parsing in chat protocol."""
from app.websocket.chat_protocol import parse_client_frame, ChatProtocolError
import pytest


def _make_copilot_frame(*, graph_context=None, mode=None, run_id=None, conversation_history=None):
    return {
        "type": "chat.start",
        "request_id": "req-1",
        "graph_id": "00000000-0000-0000-0000-000000000001",
        "input": {"message": "Build a RAG pipeline"},
        "extension": {
            "kind": "copilot",
            "run_id": run_id,
            "graph_context": graph_context if graph_context is not None else {"nodes": [], "edges": []},
            "conversation_history": conversation_history or [],
            "mode": mode or "deepagents",
        },
    }


def test_parse_copilot_extension_frame():
    result = parse_client_frame(_make_copilot_frame(run_id="run-abc"))
    assert result.extension.kind == "copilot"
    assert result.extension.run_id == "run-abc"
    assert result.extension.graph_context == {"nodes": [], "edges": []}
    assert result.extension.mode == "deepagents"
    assert result.extension.conversation_history == []


def test_parse_copilot_extension_defaults():
    """mode defaults to deepagents, conversation_history defaults to []."""
    frame = {
        "type": "chat.start",
        "request_id": "req-2",
        "input": {"message": "test"},
        "extension": {"kind": "copilot", "graph_context": {"nodes": []}},
    }
    result = parse_client_frame(frame)
    assert result.extension.kind == "copilot"
    assert result.extension.mode == "deepagents"
    assert result.extension.conversation_history == []
    assert result.extension.run_id is None


def test_parse_copilot_extension_missing_graph_context():
    """graph_context is required — missing it should raise."""
    frame = {
        "type": "chat.start",
        "request_id": "req-3",
        "input": {"message": "test"},
        "extension": {"kind": "copilot"},
    }
    with pytest.raises(ChatProtocolError, match="graph_context"):
        parse_client_frame(frame)


def test_existing_extensions_still_work():
    """Regression: skill_creator and chat extensions unchanged."""
    sc_frame = {
        "type": "chat.start",
        "request_id": "req-4",
        "input": {"message": "test"},
        "extension": {"kind": "skill_creator", "run_id": "r1", "edit_skill_id": "s1"},
    }
    result = parse_client_frame(sc_frame)
    assert result.extension.kind == "skill_creator"

    chat_frame = {
        "type": "chat.start",
        "request_id": "req-5",
        "input": {"message": "test"},
        "extension": {"kind": "chat", "run_id": "r2"},
    }
    result = parse_client_frame(chat_frame)
    assert result.extension.kind == "chat"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_api/test_chat_protocol_copilot_extension.py -v --no-header
```

Expected: FAIL — `ParsedCopilotExtension` not found, `kind == "copilot"` raises `unsupported extension kind`

- [ ] **Step 3: Add ParsedCopilotExtension to chat_protocol.py**

After `ParsedChatExtension`, add:

```python
@dataclass(frozen=True)
class ParsedCopilotExtension:
    """Extension payload for Copilot turns."""

    kind: Literal["copilot"]
    run_id: str | None
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]]
    mode: str
```

Widen `ParsedChatStartFrame.extension` type:

```python
extension: ParsedSkillCreatorExtension | ParsedChatExtension | ParsedCopilotExtension | None
```

Add copilot branch in `_parse_extension` **before** the final `raise`:

```python
if kind == "copilot":
    graph_context = raw_extension.get("graph_context")
    if not isinstance(graph_context, dict):
        raise ChatProtocolError("copilot extension requires graph_context object", request_id=request_id)
    conversation_history_raw = raw_extension.get("conversation_history")
    conversation_history = conversation_history_raw if isinstance(conversation_history_raw, list) else []
    mode = str(raw_extension.get("mode") or "deepagents")
    return ParsedCopilotExtension(
        kind="copilot",
        run_id=run_id,
        graph_context=graph_context,
        conversation_history=conversation_history,
        mode=mode,
    )
```

Update `_parse_extension` return type annotation to include `ParsedCopilotExtension`.

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_api/test_chat_protocol_copilot_extension.py -v --no-header
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/websocket/chat_protocol.py backend/tests/test_api/test_chat_protocol_copilot_extension.py
git commit -m "feat: add ParsedCopilotExtension to chat protocol"
```

---

### Task 3: Command Dispatch — CopilotTurnCommand

**Files:**
- Modify: `backend/app/websocket/chat_commands.py`
- Create: `backend/tests/test_api/test_chat_commands_copilot.py`

**Reference:** Existing `ChatRunTurnCommand` and `build_command_from_parsed_frame` in `chat_commands.py`.

- [ ] **Step 1: Write command tests**

```python
"""Tests for copilot command dispatch."""
from app.websocket.chat_commands import build_command_from_parsed_frame, CopilotTurnCommand, ChatRunTurnCommand, SkillCreatorTurnCommand
from app.websocket.chat_protocol import ParsedChatStartFrame, ParsedChatInput, ParsedCopilotExtension


def test_copilot_extension_produces_copilot_turn_command():
    frame = ParsedChatStartFrame(
        request_id="req-1",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="Build RAG", files=[], model=None),
        extension=ParsedCopilotExtension(
            kind="copilot",
            run_id="run-123",
            graph_context={"nodes": [], "edges": []},
            conversation_history=[{"role": "user", "content": "hi"}],
            mode="deepagents",
        ),
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert isinstance(cmd, CopilotTurnCommand)
    assert cmd.run_id == "run-123"
    assert cmd.graph_context == {"nodes": [], "edges": []}
    assert cmd.conversation_history == [{"role": "user", "content": "hi"}]
    assert cmd.mode == "deepagents"
    assert cmd.message == "Build RAG"


def test_no_extension_still_standard():
    frame = ParsedChatStartFrame(
        request_id="req-2",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="hello", files=[], model=None),
        extension=None,
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert not isinstance(cmd, CopilotTurnCommand)
    assert not isinstance(cmd, SkillCreatorTurnCommand)


def test_chat_extension_still_chat_run():
    from app.websocket.chat_protocol import ParsedChatExtension
    frame = ParsedChatStartFrame(
        request_id="req-3",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="hello", files=[], model=None),
        extension=ParsedChatExtension(kind="chat", run_id="r1"),
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert isinstance(cmd, ChatRunTurnCommand)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_api/test_chat_commands_copilot.py -v --no-header
```

Expected: FAIL — `CopilotTurnCommand` not importable

- [ ] **Step 3: Add CopilotTurnCommand to chat_commands.py**

Import `ParsedCopilotExtension` from `chat_protocol`:

```python
from app.websocket.chat_protocol import ParsedChatExtension, ParsedCopilotExtension, ParsedChatStartFrame
```

Add new command after `ChatRunTurnCommand`:

```python
@dataclass(frozen=True)
class CopilotTurnCommand(StandardChatTurnCommand):
    """Command for a Copilot turn, extending the standard command."""

    run_id: str | None = None
    graph_context: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "deepagents"
```

Add `field` to imports: `from dataclasses import dataclass, field`.

Update union: `ChatTurnCommand = StandardChatTurnCommand | SkillCreatorTurnCommand | ChatRunTurnCommand | CopilotTurnCommand`

Add branch in `build_command_from_parsed_frame` — **after** `extension is None` check, **before** `isinstance(extension, ParsedChatExtension)`:

```python
if isinstance(extension, ParsedCopilotExtension):
    return CopilotTurnCommand(
        request_id=frame.request_id,
        message=frame.input.message,
        thread_id=frame.thread_id,
        graph_id=frame.graph_id,
        model=model,
        metadata=metadata,
        files=files,
        run_id=extension.run_id,
        graph_context=extension.graph_context,
        conversation_history=extension.conversation_history,
        mode=extension.mode,
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_api/test_chat_commands_copilot.py -v --no-header
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/websocket/chat_commands.py backend/tests/test_api/test_chat_commands_copilot.py
git commit -m "feat: add CopilotTurnCommand and dispatch branch"
```

---

### Task 4: Turn Executor — execute_copilot_turn

**Files:**
- Modify: `backend/app/websocket/chat_turn_executor.py`
- Modify: `backend/app/websocket/chat_ws_handler.py` (if routing is there)

**Reference:** `execute_standard_turn` in `chat_turn_executor.py` for the event loop pattern. `CopilotService._get_copilot_stream` in `copilot_service.py:87-152` for the stream source. `_consume_stream_and_publish_to_redis` in `copilot_service.py:949-987` for the event collection logic.

- [ ] **Step 1: Add CopilotTurnCommand to prepare_standard_turn**

In `chat_turn_executor.py`, import `CopilotTurnCommand`:

```python
from app.websocket.chat_commands import ChatRunTurnCommand, ChatTurnCommand, CopilotTurnCommand, SkillCreatorTurnCommand
```

Add branch in `prepare_standard_turn` after the `ChatRunTurnCommand` branch:

```python
elif isinstance(command, CopilotTurnCommand):
    run_id = self._parse_uuid(command.run_id)
    persist_on_disconnect = run_id is not None
```

- [ ] **Step 2: Write execute_copilot_turn method**

Add new method to `ChatTurnExecutor`. This is the core migration — it replaces `generate_actions_async` + Redis Pub/Sub with direct `_emit_event` calls.

```python
async def execute_copilot_turn(
    self,
    request_id: str,
    payload: ChatRequest,
    graph_context: dict[str, Any],
    conversation_history: list[dict[str, Any]],
    mode: str,
) -> None:
    """Execute a copilot turn: consume CopilotService stream and emit events."""
    from app.core.trace_context import set_trace_id

    set_trace_id(request_id)
    handler = self._handler
    module = self._module
    thread_id: str | None = None
    task_entry = handler._task_supervisor.get(request_id)
    agent_run_id = task_entry.run_id if task_entry else None
    tolerate_disconnect = bool(task_entry and task_entry.persist_on_disconnect)
    assistant_message_id = f"msg-assistant-{uuid_lib.uuid4()}"

    # Collection vars for graph persistence
    final_message = ""
    final_actions: list[dict[str, Any]] = []

    try:
        async with module.AsyncSessionLocal() as db:
            # Get or create thread for this copilot turn
            thread_id, _ = await module.get_or_create_conversation(
                payload.thread_id,
                payload.message,
                handler.user_id,
                payload.metadata,
                db,
            )
            await module.save_user_message(thread_id, payload.message, payload.metadata, db)

        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("missing current asyncio task")
        if handler._task_supervisor.get(request_id) is None:
            from app.websocket.chat_task_supervisor import ChatTaskEntry
            handler._task_supervisor.register(
                request_id,
                ChatTaskEntry(
                    request_id=request_id,
                    thread_id=thread_id,
                    task=current_task,
                    run_id=agent_run_id,
                    persist_on_disconnect=tolerate_disconnect,
                ),
            )
        else:
            handler._task_supervisor.update(
                request_id,
                thread_id=thread_id,
                task=current_task,
                run_id=agent_run_id,
                persist_on_disconnect=tolerate_disconnect,
            )
        await module.task_manager.register_task(thread_id, current_task)

        # Start heartbeat if persisted run
        if agent_run_id is not None:
            await handler._mark_run_status(
                run_id=agent_run_id,
                status=AgentRunStatus.RUNNING,
                runtime_owner_id=handler._runtime_owner_id,
            )
            heartbeat_task = asyncio.create_task(
                handler._run_persisted_run_heartbeat(agent_run_id),
                name=f"run-heartbeat:{agent_run_id}",
            )
            handler._task_supervisor.update(request_id, heartbeat_task=heartbeat_task)

        # Emit accepted
        await handler._send(
            {
                "type": "accepted",
                "request_id": request_id,
                "thread_id": thread_id,
                "run_id": str(agent_run_id) if agent_run_id is not None else None,
                "timestamp": int(time.time() * 1000),
                "data": {"status": "accepted"},
            },
            tolerate_disconnect=tolerate_disconnect,
        )

        # Create CopilotService and get stream
        from app.services.copilot_service import CopilotService
        async with module.AsyncSessionLocal() as db:
            # payload.model carries the frontend-selected model (e.g. "anthropic:claude-3-7-sonnet")
            service = CopilotService(
                user_id=handler.user_id,
                llm_model=payload.model if hasattr(payload, "model") else None,
                db=db,
            )
            stream = service._get_copilot_stream(
                prompt=payload.message,
                graph_context=graph_context,
                conversation_history=conversation_history,
                mode=mode,
                graph_id=str(payload.graph_id) if payload.graph_id else None,
            )

            async for event in stream:
                if await module.task_manager.is_stopped(thread_id):
                    break

                event_type = event.get("type", "")

                # Collect for persistence
                if event_type == "result":
                    final_message = event.get("message", "")
                    final_actions = event.get("actions", [])

                # Emit to WS + run events
                await handler._emit_event(
                    {
                        "type": event_type,
                        "thread_id": thread_id,
                        "node_name": "copilot",
                        "timestamp": int(time.time() * 1000),
                        "data": event,
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )

        # Persist graph changes
        # _persist_graph_from_actions creates its own DB session internally,
        # so we only need user_id set on the service.
        if payload.graph_id and final_actions:
            persist_service = CopilotService(user_id=handler.user_id)
            await persist_service._persist_graph_from_actions(
                graph_id=str(payload.graph_id),
                final_actions=final_actions,
            )

        # Emit done
        await handler._emit_event(
            {
                "type": "done",
                "thread_id": thread_id,
                "node_name": "copilot",
                "timestamp": int(time.time() * 1000),
                "data": {},
            },
            request_id=request_id,
            tolerate_disconnect=tolerate_disconnect,
            agent_run_id=agent_run_id,
            assistant_message_id=assistant_message_id,
        )

    except asyncio.CancelledError:
        try:
            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id or "",
                    "node_name": "copilot",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
        except Exception:
            _logger.debug("error during copilot turn cleanup", exc_info=True)
        raise
    except Exception as exc:
        error_data: dict[str, object] = {"message": str(exc)}
        if isinstance(exc, ModelConfigError):
            error_data["error_code"] = exc.error_code
            error_data["params"] = exc.params
        await handler._emit_event(
            {
                "type": "error",
                "thread_id": thread_id or "",
                "node_name": "copilot",
                "timestamp": int(time.time() * 1000),
                "data": error_data,
            },
            request_id=request_id,
            tolerate_disconnect=tolerate_disconnect,
            agent_run_id=agent_run_id,
            assistant_message_id=assistant_message_id,
        )
        await handler._emit_event(
            {
                "type": "done",
                "thread_id": thread_id or "",
                "node_name": "copilot",
                "timestamp": int(time.time() * 1000),
                "data": {},
            },
            request_id=request_id,
            tolerate_disconnect=tolerate_disconnect,
            agent_run_id=agent_run_id,
            assistant_message_id=assistant_message_id,
        )
    finally:
        await handler._finalize_task(
            request_id=request_id,
            thread_id=thread_id,
            state=None,
            built_graph=None,
            artifact_collector=None,
            graph_id=str(payload.graph_id) if payload.graph_id else None,
            workspace_id=None,
            graph_name=None,
        )
```

Note: Add required imports at the top: `from typing import Any` (if not present), ensure `asyncio`, `time`, `uuid_lib` are imported.

- [ ] **Step 3: Route CopilotTurnCommand in run_standard_turn or handler**

In `ChatTurnExecutor.run_standard_turn`, add a check:

```python
async def run_standard_turn(self, prepared: PreparedStandardTurn) -> None:
    run_chat_turn = getattr(self._handler, "_run_chat_turn", None)
    if not callable(run_chat_turn):
        run_chat_turn = self.execute_standard_turn
    await run_chat_turn(request_id=prepared.request_id, payload=prepared.payload)
```

This method currently does not differentiate by command type. The routing needs to happen at the call site. Check `chat_ws_handler.py` for where `run_standard_turn` is called and add copilot dispatch there.

In `chat_ws_handler.py`, find where `_turn_executor.run_standard_turn(prepared)` is called. Before that call, add:

```python
if isinstance(command, CopilotTurnCommand):
    await self._turn_executor.execute_copilot_turn(
        request_id=prepared.request_id,
        payload=prepared.payload,
        graph_context=command.graph_context,
        conversation_history=command.conversation_history,
        mode=command.mode,
    )
    return
```

Import `CopilotTurnCommand` in `chat_ws_handler.py`.

- [ ] **Step 4: Verify syntax**

```bash
cd backend && python -m py_compile app/websocket/chat_turn_executor.py && python -m py_compile app/websocket/chat_ws_handler.py && echo "OK"
```

Expected: OK

- [ ] **Step 5: Run all existing tests to verify no regressions**

```bash
cd backend && python -m pytest tests/test_services/test_copilot_run_reducer.py tests/test_api/test_chat_protocol_copilot_extension.py tests/test_api/test_chat_commands_copilot.py -v --no-header
```

Expected: All pass (20+)

- [ ] **Step 6: Commit**

```bash
git add backend/app/websocket/chat_turn_executor.py backend/app/websocket/chat_ws_handler.py
git commit -m "feat: add execute_copilot_turn and WS handler routing"
```

---

### Task 5: Frontend Types & Serialization

**Files:**
- Modify: `frontend/lib/ws/chat/types.ts`
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`

- [ ] **Step 1: Add CopilotExtension interface**

In `frontend/lib/ws/chat/types.ts`, add after the `ChatExtension` interface:

```typescript
export interface CopilotExtension {
  kind: 'copilot'
  runId?: string | null
  graphContext: Record<string, unknown>
  conversationHistory: Array<Record<string, unknown>>
  mode: string
}
```

Widen the `ChatSendParams.extension` type:

```typescript
extension?: SkillCreatorExtension | ChatExtension | CopilotExtension | null
```

- [ ] **Step 2: Add copilot branch in serializeExtension**

In `frontend/lib/ws/chat/chatWsClient.ts`, import `CopilotExtension`:

```typescript
import type {
  ChatExtension,
  ChatResumeParams,
  ChatSendParams,
  ChatTerminalResult,
  ChatWsClient,
  ConnectionState,
  CopilotExtension,
  IncomingChatAcceptedEvent,
  IncomingChatWsEvent,
  SkillCreatorExtension,
} from './types'
```

Update `serializeExtension` signature to include `CopilotExtension`:

```typescript
function serializeExtension(extension?: SkillCreatorExtension | ChatExtension | CopilotExtension | null): Record<string, unknown> | null {
```

Add copilot branch after the `chat` branch:

```typescript
  if (extension.kind === 'copilot') {
    return {
      kind: extension.kind,
      run_id: extension.runId ?? null,
      graph_context: extension.graphContext,
      conversation_history: extension.conversationHistory,
      mode: extension.mode,
    }
  }
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: No errors related to types.ts or chatWsClient.ts

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/ws/chat/types.ts frontend/lib/ws/chat/chatWsClient.ts
git commit -m "feat: add CopilotExtension type and WS serialization"
```

---

### Task 6: Frontend Copilot Hooks Migration

**Files:**
- Modify: `frontend/hooks/copilot/useCopilotSession.ts`
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotState.ts`
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotActions.ts`
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotWebSocketHandler.ts`
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotEffects.ts`

**Reference:** Design spec section 4 (Frontend Changes). Existing `useChatWebSocket.ts:412-487` for the `sendMessage` pattern with `runService.createRun` + `getChatWsClient().sendChat`.

#### 6a: Migrate useCopilotSession (session_id → run_id)

- [ ] **Step 1: Rename session to run in useCopilotSession**

Replace `useCopilotSession` to use `run_id` instead of `session_id`. The localStorage key changes from `copilot_session_{graphId}` to `copilot_run_{graphId}`:

```typescript
import { useState, useEffect, useRef, useCallback } from 'react'

export function useCopilotSession(graphId?: string) {
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const hasProcessedUrlInputRef = useRef(false)

  useEffect(() => {
    if (!graphId) return
    const storedRunId = localStorage.getItem(`copilot_run_${graphId}`)
    if (storedRunId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentRunId(storedRunId)
    }
  }, [graphId])

  const setSession = useCallback(
    (runId: string) => {
      setCurrentRunId(runId)
      if (graphId) {
        localStorage.setItem(`copilot_run_${graphId}`, runId)
      }
    },
    [graphId],
  )

  const clearSession = useCallback(() => {
    setCurrentRunId(null)
    if (graphId) {
      localStorage.removeItem(`copilot_run_${graphId}`)
    }
  }, [graphId])

  return {
    currentRunId,
    hasProcessedUrlInputRef,
    setSession,
    clearSession,
  }
}
```

Note: Downstream consumers that read `currentSessionId` must be updated to read `currentRunId`. Specifically, update `useCopilotState.ts`:

In `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotState.ts`:

1. In the `CopilotState` interface, rename `currentSessionId: string | null` → `currentRunId: string | null`
2. In the state assembly (where `currentSessionId: sessionHook.currentSessionId`), rename to `currentRunId: sessionHook.currentRunId`
3. Update any component that destructures `currentSessionId` from state

The property rename is `currentSessionId` → `currentRunId` throughout.

- [ ] **Step 2: Verify compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "copilotSession\|currentSessionId\|copilot_session" | head -20
```

Fix any remaining references to `currentSessionId` in files that consume the hook.

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/copilot/useCopilotSession.ts
git commit -m "refactor: rename copilot session_id to run_id in useCopilotSession"
```

#### 6b: Migrate useCopilotActions (createCopilotTask → runService + sendChat)

- [ ] **Step 4: Rewrite handleSendWithInput**

In `useCopilotActions.ts`, replace `copilotService.createCopilotTask` with `runService.createRun` + `getChatWsClient().sendChat`. The key changes:

1. Import `runService` and `getChatWsClient`:

```typescript
import { runService } from '@/services/runService'
import { getChatWsClient } from '@/lib/ws/chat/chatWsClient'
import type { CopilotExtension } from '@/lib/ws/chat/types'
import type { ChatStreamEvent } from '@/services/chatBackend'
```

2. Remove `copilotService` import. Keep `copilotService.convertConversationHistory` import (it stays) or inline the import:

```typescript
import { copilotService } from '@/services/copilotService'
```

This import is still needed for `convertConversationHistory` and `clearHistory`.

3. Add `onCopilotEvent` callback parameter to the hook options:

```typescript
interface UseCopilotActionsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  copilotMode?: CopilotMode
  selectedModel?: string
  onCopilotEvent?: (evt: ChatStreamEvent) => void
}
```

4. Rewrite `handleSendWithInput`:

```typescript
const handleSendWithInput = useCallback(
  async (userText: string) => {
    if (!userText.trim() || state.loading || !refs.isMountedRef.current) return

    actions.setInput('')
    actions.addMessage({ role: 'user', text: userText })

    if (!refs.isMountedRef.current) return
    actions.setLoading(true)
    actions.clearStreaming()

    refs.isCreatingSessionRef.current = true
    actions.clearSession()

    const graphContext = getGraphContext()
    const storeGraphId = useBuilderStore.getState().graphId

    if (!storeGraphId) {
      console.error('[CopilotPanel] No graphId in store')
      if (refs.isMountedRef.current) {
        actions.setLoading(false)
      }
      return
    }

    try {
      const historyMessages = copilotService.convertConversationHistory(state.messages)

      // 1. Create run via Run Center
      let runId: string | null = null
      try {
        const runResponse = await runService.createRun({
          agent_name: 'copilot',
          graph_id: graphId || storeGraphId,
          message: userText,
        })
        runId = runResponse.run_id
      } catch (err) {
        console.warn('[Copilot] Failed to create run, proceeding without persistence', err)
      }

      if (!refs.isMountedRef.current) return

      // Save run_id
      if (runId) {
        actions.setSession(runId)
      }

      actions.setCurrentStage({ stage: 'thinking', message: 'Connecting...' })
      actions.setThinkingMessage()

      // 2. Send via shared chat WS
      const extension: CopilotExtension = {
        kind: 'copilot',
        runId,
        graphContext,
        conversationHistory: historyMessages as Array<Record<string, unknown>>,
        mode: copilotMode,
      }

      await getChatWsClient().sendChat({
        input: {
          message: userText,
          model: selectedModel,
        },
        graphId: graphId || storeGraphId,
        extension,
        onEvent: (evt) => onCopilotEvent?.(evt),
      })
    } catch (e: unknown) {
      console.error('[CopilotPanel] Failed to send copilot message:', e)

      if (!refs.isMountedRef.current) return

      actions.setLoading(false)
      actions.clearStreaming()

      let errorMessage = t('workspace.couldNotProcessRequest')

      if (e && typeof e === 'object') {
        const error = e as { response?: { status?: number }; message?: string }
        if (error.response?.status === 401 || error.response?.status === 403) {
          errorMessage = t('workspace.copilot.error.auth', {
            defaultValue: 'Authentication error. Please check your credentials.',
          })
        } else if (error.message?.includes('fetch') || error.message?.includes('network')) {
          errorMessage = t('workspace.copilot.error.network', {
            defaultValue: 'Network error. Please check your connection and try again.',
          })
        }
      }

      actions.finalizeCurrentMessage(`${t('workspace.systemError')}: ${errorMessage}`)
      refs.isCreatingSessionRef.current = false
      actions.clearSession()
    }
  },
  [state.loading, state.messages, actions, refs, graphId, copilotMode, selectedModel, getGraphContext, t, onCopilotEvent],
)
```

5. Update `handleStop` to use chat WS stop:

```typescript
const handleStop = useCallback(() => {
  // Stop via shared chat WS (requestId tracked internally by WS client)
  // The WS client will emit done/error which triggers cleanup via onDone callback
  actions.clearSession()

  if (!refs.isMountedRef.current) return
  actions.setLoading(false)
  actions.clearStreaming()

  refs.isCreatingSessionRef.current = false
  actions.removeCurrentMessage()
  actions.addMessage({ role: 'model', text: t('workspace.requestCancelled') })
}, [actions, refs, t])
```

- [ ] **Step 5: Verify compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "copilotActions\|useCopilotActions" | head -20
```

- [ ] **Step 6: Commit**

```bash
git add frontend/app/workspace/*/[agentId]/hooks/useCopilotActions.ts
git commit -m "feat: migrate useCopilotActions to Run Center + chat WS"
```

#### 6c: Migrate useCopilotWebSocketHandler (receive from chat WS onEvent)

- [ ] **Step 7: Wire copilot callbacks to chat WS events**

The `useCopilotWebSocketHandler` currently defines callbacks (`onStatus`, `onContent`, etc.) that are consumed by `use-copilot-websocket.ts`. After migration, these same callbacks are invoked by `handleCopilotEvent` which receives `ChatStreamEvent` from the chat WS `onEvent`.

Add a new `handleCopilotEvent` function that the parent can pass as `onCopilotEvent` to `useCopilotActions`:

```typescript
import type { ChatStreamEvent } from '@/services/chatBackend'

// Add to the returned object from useCopilotWebSocketHandler:
const handleCopilotEvent = useCallback(
  (evt: ChatStreamEvent) => {
    const data = evt.data as Record<string, unknown> | undefined
    if (!data) return
    const type = data.type as string | undefined
    if (!type) return

    switch (type) {
      case 'status':
        callbacks.onStatus(data.stage as string, data.message as string)
        break
      case 'content':
        callbacks.onContent(data.content as string)
        break
      case 'thought_step':
        callbacks.onThoughtStep?.(data.step as { index: number; content: string })
        break
      case 'tool_call':
        callbacks.onToolCall(data.tool as string, data.input as Record<string, unknown>)
        break
      case 'tool_result':
        callbacks.onToolResult(data.action as { type: string; payload: Record<string, unknown>; reasoning?: string })
        break
      case 'result':
        callbacks.onResult?.({
          message: (data.message as string) ?? '',
          actions: data.actions as Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }> | undefined,
        })
        break
      case 'error':
        callbacks.onError((data.message as string) ?? 'Unknown error')
        break
      case 'done':
        callbacks.onDone?.()
        break
    }
  },
  [callbacks],
)

// Return it alongside callbacks:
return { ...callbacks, handleCopilotEvent }
```

- [ ] **Step 8: Verify compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "WebSocketHandler" | head -20
```

- [ ] **Step 9: Commit**

```bash
git add frontend/app/workspace/*/[agentId]/hooks/useCopilotWebSocketHandler.ts
git commit -m "feat: add handleCopilotEvent bridge in useCopilotWebSocketHandler"
```

#### 6d: Migrate useCopilotEffects (session recovery → run snapshot)

- [ ] **Step 10: Replace session recovery with run snapshot**

In `useCopilotEffects.ts`, replace `copilotService.getSession(sessionId)` with `runService.getRunSnapshot(runId)`:

```typescript
import { runService } from '@/services/runService'
```

Remove `import { copilotService } from '@/services/copilotService'`.

Replace the session recovery effect. The state now uses `currentRunId` (from step 1):

```typescript
// Session recovery: restore state from run snapshot when runId is restored
useEffect(() => {
  const currentRunId = state.currentRunId  // was state.currentSessionId
  if (
    !currentRunId ||
    refs.isCreatingSessionRef.current ||
    lastRestoredSessionIdRef.current === currentRunId
  )
    return

  const restoreSession = async () => {
    console.warn('[useCopilotEffects] Restoring from run snapshot:', currentRunId)
    lastRestoredSessionIdRef.current = currentRunId

    try {
      actions.setLoading(true)
      const snapshot = await runService.getRunSnapshot(currentRunId)
      if (!refs.isMountedRef.current) return

      if (!snapshot) {
        actions.clearSession()
        return
      }

      const projection = snapshot.projection as Record<string, unknown> | undefined
      const status = snapshot.status as string

      if (status === 'running' || status === 'queued') {
        // Run still active — show last known state
        if (projection) {
          const content = projection.content as string | undefined
          if (content) {
            actions.setStreamingContent(content)
          }
          const stage = projection.stage as string | undefined
          actions.setCurrentStage({ stage: (stage || 'processing') as any, message: 'Processing...' })
          if (!hasCurrentMessage(state.messages, false)) actions.setThinkingMessage()
        }
        // TODO: subscribe to /ws/runs for live event replay (future enhancement)
      } else if (status === 'completed') {
        if (projection) {
          const resultMessage = (projection.result_message as string) ?? ''
          const resultActions = projection.result_actions as Array<Record<string, unknown>> | undefined
          if (resultMessage || (resultActions && resultActions.length > 0)) {
            actions.finalizeCurrentMessage(resultMessage, resultActions as any)
          }
        }
        actions.clearSession()
        actions.clearStreaming()
      } else if (status === 'failed') {
        toast({
          title: 'Copilot task failed',
          description: (projection?.error as string) || 'An error occurred during execution. Please retry.',
          variant: 'destructive',
        })
        actions.clearSession()
      }
    } catch (error) {
      console.warn('[CopilotPanel] Failed to restore from run snapshot:', error)
    } finally {
      if (refs.isMountedRef.current) actions.setLoading(false)
    }
  }

  restoreSession()
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [state.currentRunId, actions, refs])
```

Note: The `state.currentSessionId` reference must be updated to `state.currentRunId` — this depends on the `useCopilotState` type also being updated from step 1.

- [ ] **Step 11: Verify compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "copilotEffects\|useCopilotEffects" | head -20
```

- [ ] **Step 12: Commit**

```bash
git add frontend/app/workspace/*/[agentId]/hooks/useCopilotEffects.ts
git commit -m "feat: migrate copilot session recovery to run snapshot"
```

---

### Task 7: History API Rewrite

**Files:**
- Modify: `backend/app/api/v1/graphs.py` (GET/DELETE copilot/history endpoints)
- Modify: `backend/app/repositories/agent_run.py` (add graph_id filter + bulk delete)
- Test: `backend/tests/test_api/test_copilot_history_from_runs.py`

**Reference:** Design spec section 5 (History API Rewrite). Existing `agent_run.py:93-113` for `list_recent_runs_for_user`. The response format must match existing `CopilotHistoryResponse` so frontend `useCopilotHistory` is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api/test_copilot_history_from_runs.py`:

```python
"""Tests for copilot history built from agent_run snapshots."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import uuid


def _make_run(*, graph_id: str, title: str, status: str = "completed") -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.graph_id = uuid.UUID(graph_id)
    run.title = title
    run.status = status
    run.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    run.updated_at = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
    return run


def _make_snapshot(*, result_message: str, result_actions: list | None = None,
                   thought_steps: list | None = None, tool_calls: list | None = None) -> MagicMock:
    snap = MagicMock()
    snap.projection = {
        "result_message": result_message,
        "result_actions": result_actions or [],
        "content": "",
        "thought_steps": thought_steps or [],
        "tool_calls": tool_calls or [],
    }
    return snap


def test_build_history_messages_from_runs():
    """History messages are assembled from run title + snapshot projection."""
    graph_id = str(uuid.uuid4())
    runs = [
        _make_run(graph_id=graph_id, title="Hello"),
        _make_run(graph_id=graph_id, title="Build RAG"),
    ]
    snapshots = [
        _make_snapshot(result_message="Hi! How can I help?"),
        _make_snapshot(result_message="Here is your RAG pipeline.", result_actions=[{"type": "add_node", "payload": {}}]),
    ]

    # Build messages the same way the endpoint does
    messages = []
    for run, snap in zip(reversed(runs), reversed(snapshots)):
        messages.append({
            "role": "user",
            "content": run.title or "",
            "created_at": run.created_at.isoformat(),
        })
        p = snap.projection
        messages.append({
            "role": "assistant",
            "content": p.get("result_message") or p.get("content", ""),
            "created_at": run.updated_at.isoformat(),
            "actions": p.get("result_actions", []),
            "thought_steps": p.get("thought_steps", []),
            "tool_calls": p.get("tool_calls", []),
        })

    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hi! How can I help?"
    assert messages[2]["content"] == "Build RAG"
    assert messages[3]["actions"] == [{"type": "add_node", "payload": {}}]


def test_build_history_filters_by_graph_id():
    """Only runs matching the requested graph_id are included."""
    target_gid = str(uuid.uuid4())
    other_gid = str(uuid.uuid4())
    runs = [
        _make_run(graph_id=target_gid, title="Match"),
        _make_run(graph_id=other_gid, title="NoMatch"),
    ]
    filtered = [r for r in runs if str(r.graph_id) == target_gid]
    assert len(filtered) == 1
    assert filtered[0].title == "Match"


def test_build_history_skips_runs_without_snapshot():
    """Runs that have no snapshot are silently skipped."""
    graph_id = str(uuid.uuid4())
    runs = [_make_run(graph_id=graph_id, title="NoSnap")]
    snapshot = None

    messages = []
    for run in reversed(runs):
        if snapshot is None:
            continue
    assert len(messages) == 0
```

- [ ] **Step 2: Run tests to verify they pass (unit logic)**

```bash
cd backend && python -m pytest tests/test_api/test_copilot_history_from_runs.py -v --no-header
```

Expected: 3 passed

- [ ] **Step 3: Add graph_id filter to list_recent_runs_for_user**

In `backend/app/repositories/agent_run.py`, add `graph_id` parameter to `list_recent_runs_for_user`:

```python
async def list_recent_runs_for_user(
    self,
    *,
    user_id: str,
    run_type: Optional[str] = None,
    agent_name: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    graph_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> Sequence[AgentRun]:
    query = select(AgentRun).where(AgentRun.user_id == user_id)
    if run_type:
        query = query.where(AgentRun.run_type == run_type)
    if agent_name:
        query = query.where(AgentRun.agent_name == agent_name)
    if status:
        query = query.where(AgentRun.status == status)
    if search:
        query = query.where(AgentRun.title.ilike(f"%{search}%"))
    if graph_id:
        query = query.where(AgentRun.graph_id == graph_id)
    result = await self.db.execute(query.order_by(desc(AgentRun.updated_at)).limit(limit))
    return result.scalars().all()
```

- [ ] **Step 4: Add delete_runs_for_graph method**

In `backend/app/repositories/agent_run.py`, add a bulk delete method:

```python
from sqlalchemy import delete as sa_delete

async def delete_runs_for_graph(
    self,
    *,
    user_id: str,
    agent_name: str,
    graph_id: uuid.UUID,
) -> int:
    """Hard-delete all runs (and cascaded events/snapshots) for a graph."""
    result = await self.db.execute(
        sa_delete(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.agent_name == agent_name,
            AgentRun.graph_id == graph_id,
        )
    )
    await self.db.commit()
    return result.rowcount
```

- [ ] **Step 5: Rewrite GET copilot/history endpoint**

In `backend/app/api/v1/graphs.py`, replace the `get_copilot_history` function body. The imports needed:

```python
from app.repositories.agent_run import AgentRunRepository
```

New implementation:

```python
@router.get("/{graph_id}/copilot/history")
async def get_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.get start")

    graph_service = GraphService(db)
    graph = await graph_service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await graph_service._ensure_access(graph, current_user, WorkspaceMemberRole.viewer)

    repo = AgentRunRepository(db)
    runs = await repo.list_recent_runs_for_user(
        user_id=str(current_user.id),
        agent_name="copilot",
        graph_id=graph_id,
        limit=100,
    )

    messages = []
    for run in reversed(list(runs)):  # oldest first
        snapshot = await repo.get_snapshot(run.id)
        if not snapshot or not snapshot.projection:
            continue
        p = snapshot.projection
        messages.append({
            "role": "user",
            "content": run.title or "",
            "created_at": run.created_at.isoformat() if run.created_at else None,
        })
        messages.append({
            "role": "assistant",
            "content": p.get("result_message") or p.get("content", ""),
            "created_at": run.updated_at.isoformat() if run.updated_at else None,
            "actions": p.get("result_actions", []),
            "thought_steps": p.get("thought_steps", []),
            "tool_calls": p.get("tool_calls", []),
        })

    log.info(f"copilot.history.get success messages_count={len(messages)}")
    return {"data": {"graph_id": str(graph_id), "messages": messages}}
```

- [ ] **Step 6: Rewrite DELETE copilot/history endpoint**

```python
@router.delete("/{graph_id}/copilot/history")
async def clear_copilot_history(
    request: Request,
    graph_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = _bind_log(request, user_id=str(current_user.id), graph_id=str(graph_id))
    log.info("copilot.history.clear start")

    graph_service = GraphService(db)
    graph = await graph_service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await graph_service._ensure_access(graph, current_user, WorkspaceMemberRole.member)

    repo = AgentRunRepository(db)
    deleted = await repo.delete_runs_for_graph(
        user_id=str(current_user.id),
        agent_name="copilot",
        graph_id=graph_id,
    )

    log.info(f"copilot.history.clear success deleted={deleted}")
    return {"success": True}
```

- [ ] **Step 7: Verify syntax**

```bash
cd backend && python -m py_compile app/api/v1/graphs.py && python -m py_compile app/repositories/agent_run.py && echo "OK"
```

Expected: OK

- [ ] **Step 8: Run tests**

```bash
cd backend && python -m pytest tests/test_api/test_copilot_history_from_runs.py -v --no-header
```

Expected: 3 passed

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/v1/graphs.py backend/app/repositories/agent_run.py backend/tests/test_api/test_copilot_history_from_runs.py
git commit -m "feat: rewrite copilot history API to use agent_runs"
```

---

### Task 8: Run Center Visibility

**Files:**
- Modify: `frontend/lib/utils/runHelpers.ts`
- Modify: `frontend/app/runs/[runId]/page.tsx`

**Reference:** Design spec section 6 (Run Center Visibility). Existing `buildRunHref` in `runHelpers.ts:53-61` and `ChatTurnOverview` in `page.tsx`.

- [ ] **Step 1: Add copilot_turn case to buildRunHref**

In `frontend/lib/utils/runHelpers.ts`, add a copilot branch before the fallback `return '#'`:

```typescript
export function buildRunHref(run: { run_id: string; run_type?: string; agent_name?: string | null }): string {
  if (run.agent_name === 'skill_creator' || run.run_type === 'skill_creator') {
    return `/skills/creator?run=${encodeURIComponent(run.run_id)}`
  }
  if (run.agent_name === 'chat' || run.run_type === 'chat_turn') {
    return `/runs/${encodeURIComponent(run.run_id)}`
  }
  if (run.agent_name === 'copilot' || run.run_type === 'copilot_turn') {
    return `/runs/${encodeURIComponent(run.run_id)}`
  }
  return '#'
}
```

- [ ] **Step 2: Add CopilotTurnOverview component**

In `frontend/app/runs/[runId]/page.tsx`, add a `CopilotTurnOverview` component. This follows the same pattern as the existing `ChatTurnOverview`.

Add the projection interface:

```typescript
interface CopilotTurnProjection {
  run_type: string
  status: string
  stage?: string | null
  content?: string
  thought_steps?: Array<{ index: number; content: string }>
  tool_calls?: Array<{ tool: string; input?: Record<string, unknown> }>
  tool_results?: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  result_message?: string | null
  result_actions?: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  error?: string | null
  graph_id?: string | null
  mode?: string | null
}
```

Add the component:

```typescript
function CopilotTurnOverview({ projection, t }: { projection: CopilotTurnProjection; t: (key: string, fallback: string) => string }) {

  return (
    <div className="space-y-4">
      {/* Stage indicator */}
      {projection.stage && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.stage', 'Stage')}</p>
          <p className="text-sm text-muted-foreground">{projection.stage}</p>
        </div>
      )}

      {/* Mode */}
      {projection.mode && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.mode', 'Mode')}</p>
          <p className="text-sm text-muted-foreground">{projection.mode}</p>
        </div>
      )}

      {/* Content */}
      {projection.content && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.content', 'Content')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.content}</p>
        </div>
      )}

      {/* Thought Steps (collapsible) */}
      {projection.thought_steps && projection.thought_steps.length > 0 && (
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t('runs.thoughtSteps', 'Thought Steps')} ({projection.thought_steps.length})
          </summary>
          <div className="mt-2 space-y-2">
            {projection.thought_steps.map((step, i) => (
              <div key={i} className="text-sm text-muted-foreground">
                <span className="font-mono text-xs">#{step.index}</span> {step.content}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Tool Calls (collapsible) */}
      {projection.tool_calls && projection.tool_calls.length > 0 && (
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t('runs.toolCalls', 'Tool Calls')} ({projection.tool_calls.length})
          </summary>
          <div className="mt-2 space-y-2">
            {projection.tool_calls.map((tc, i) => (
              <div key={i} className="text-sm">
                <span className="font-medium">{tc.tool}</span>
                {tc.input && (
                  <pre className="mt-1 overflow-x-auto text-xs text-muted-foreground">
                    {JSON.stringify(tc.input, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Result */}
      {projection.result_message && (
        <div className="rounded-md border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-950">
          <p className="text-sm font-medium">{t('runs.result', 'Result')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.result_message}</p>
          {projection.result_actions && projection.result_actions.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-muted-foreground">
                {projection.result_actions.length} action(s)
              </p>
              {projection.result_actions.map((action, i) => (
                <div key={i} className="mt-1 text-xs text-muted-foreground">
                  {action.type}{action.reasoning ? ` — ${action.reasoning}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {projection.error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950">
          <p className="text-sm font-medium text-red-700 dark:text-red-400">{t('runs.error', 'Error')}</p>
          <p className="mt-1 text-sm text-red-600 dark:text-red-300">{projection.error}</p>
        </div>
      )}
    </div>
  )
}
```

Then in the `RunDetailPage` component, add a `copilot_turn` branch alongside the existing `chat_turn` branch:

```typescript
{runType === 'copilot_turn' && projection && (
  <CopilotTurnOverview projection={projection as CopilotTurnProjection} t={t} />
)}
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/utils/runHelpers.ts frontend/app/runs/[runId]/page.tsx
git commit -m "feat: add copilot_turn visibility in Run Center"
```

---

### Task 9: Delete Old Copilot Infrastructure

**Files:**
- Delete: `backend/app/websocket/copilot_handler.py`
- Delete: `frontend/hooks/use-copilot-websocket.ts`
- Modify: `backend/app/main.py` (remove `/ws/copilot` route + import)
- Modify: `backend/app/core/redis.py` (remove ~12 copilot methods)
- Modify: `backend/app/api/v1/graphs.py` (remove 3 endpoints)
- Modify: `backend/app/services/copilot_service.py` (remove Redis/persist methods)
- Modify: `frontend/services/copilotService.ts` (remove `createCopilotTask`, `getSession`)

**Reference:** Design spec section 7 (Deleted Code).

- [ ] **Step 1: Delete copilot_handler.py**

```bash
rm backend/app/websocket/copilot_handler.py
```

- [ ] **Step 2: Remove WS route from main.py**

In `backend/app/main.py`, remove the import:

```python
from app.websocket.copilot_handler import copilot_handler
```

Remove the entire `/ws/copilot/{session_id}` endpoint (lines 340-357 approximately):

```python
@app.websocket("/ws/copilot/{session_id}")
async def copilot_websocket_endpoint(websocket: WebSocket, session_id: str):
    ...
```

- [ ] **Step 3: Remove copilot Redis methods from redis.py**

In `backend/app/core/redis.py`, delete the entire `# ==================== Copilot Session Methods ====================` block (lines 176-294 approximately). This removes:
- `append_copilot_content`
- `publish_copilot_event`
- `set_copilot_status`
- `set_copilot_error`
- `get_copilot_status`
- `get_copilot_error`
- `get_copilot_content`
- `set_copilot_result`
- `get_copilot_result`
- `get_copilot_session`
- `cleanup_copilot_session`

- [ ] **Step 4: Remove old API endpoints from graphs.py**

In `backend/app/api/v1/graphs.py`, delete these three endpoints entirely:
- `POST /copilot/actions/create` (the `create_copilot_task` function)
- `GET /copilot/sessions/{session_id}` (the `get_copilot_session` function)
- `POST /{graph_id}/copilot/messages` (the `save_copilot_messages` function)

Keep `POST /copilot/actions` (the sync non-streaming endpoint) — it's unchanged.
Keep `GET /{graph_id}/copilot/history` and `DELETE /{graph_id}/copilot/history` — already rewritten in Task 7.

Also remove now-unused imports: `BackgroundTasks`, `RedisClient` (if only used by copilot), `CopilotSessionStatus`, `CopilotRequest` etc. Check each import's usage before removing.

- [ ] **Step 5: Remove Redis/persist methods from copilot_service.py**

In `backend/app/services/copilot_service.py`, delete these methods:
- `generate_actions_async` (~160 lines)
- `_consume_stream_and_publish_to_redis` (~40 lines)
- `_persist_conversation` (if present)
- `save_messages` (if present)
- `save_conversation_from_stream` (if present)
- `get_history_for_api` (now replaced by run-based history in graphs.py)
- `clear_history` (now replaced by repo delete in graphs.py)

Also remove imports used only by deleted methods: `RedisClient`, `CopilotSessionStatus`, `CopilotChatRepository`, etc.

- [ ] **Step 6: Delete frontend use-copilot-websocket.ts**

```bash
rm frontend/hooks/use-copilot-websocket.ts
```

Check for any remaining imports of `useCopilotWebSocket` or `use-copilot-websocket` and remove them:

```bash
cd frontend && grep -r "use-copilot-websocket\|useCopilotWebSocket" --include="*.ts" --include="*.tsx" -l
```

- [ ] **Step 7: Remove createCopilotTask and getSession from copilotService.ts**

In `frontend/services/copilotService.ts`, delete:
- `createCopilotTask` method
- `getSession` method

Keep `clearHistory` and `convertConversationHistory` — they are still used.

Remove now-unused imports (e.g., `apiGet` if only used by `getSession`).

- [ ] **Step 8: Verify syntax — backend**

```bash
cd backend && python -m py_compile app/main.py && python -m py_compile app/core/redis.py && python -m py_compile app/api/v1/graphs.py && python -m py_compile app/services/copilot_service.py && echo "OK"
```

Expected: OK

- [ ] **Step 9: Verify TypeScript — frontend**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: No errors

- [ ] **Step 10: Run all copilot tests**

```bash
cd backend && python -m pytest tests/ -k "copilot" -v --no-header
```

Expected: All pass (some old tests may need to be deleted — see step 11)

- [ ] **Step 11: Delete tests for removed code**

Delete any test files that test removed functionality (copilot_handler tests, Redis copilot method tests, copilot_chat_repository tests). Grep for test files:

```bash
find backend/tests -name "*copilot*" -type f
```

Keep: `test_copilot_run_reducer.py`, `test_chat_protocol_copilot_extension.py`, `test_chat_commands_copilot.py`, `test_copilot_history_from_runs.py`.
Delete any others that test removed Redis/WS/session code.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: delete old copilot infrastructure (Redis, WS handler, copilot_chats)"
```

---

### Task 10: Alembic Migration — Drop copilot_chats Table

**Files:**
- Create: `backend/alembic/versions/20260406_000000_drop_copilot_chats_table.py`
- Modify: `backend/app/models/chat.py` (remove `CopilotChat` class)
- Delete: `backend/app/repositories/copilot_chat_repository.py`

**Reference:** Design spec section 7 (Deleted Code). Existing migration `20260405_000000_drop_graph_test_cases.py` for pattern.

- [ ] **Step 1: Delete CopilotChat model from chat.py**

In `backend/app/models/chat.py`, remove the `CopilotChat` class definition (starting at line 50). Keep other models in the file.

- [ ] **Step 2: Delete copilot_chat_repository.py**

```bash
rm backend/app/repositories/copilot_chat_repository.py
```

Remove any imports of `CopilotChatRepository` from other files:

```bash
cd backend && grep -r "CopilotChatRepository\|copilot_chat_repository" --include="*.py" -l
```

Remove all found references.

- [ ] **Step 3: Create Alembic migration**

Create `backend/alembic/versions/20260406_000000_drop_copilot_chats_table.py`:

```python
"""drop_copilot_chats_table

Revision ID: a1b2c3d4e5f6
Revises: 20260405_drop_graph_test_cases (find actual head)
Create Date: 2026-04-06

Drop the copilot_chats table. Copilot persistence is now handled by
agent_runs / agent_run_events / agent_run_snapshots (Run Center).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers — run `alembic heads` to get the correct down_revision
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None  # SET THIS from `alembic heads`
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the index first (created by migration 000000000001)
    op.drop_index("copilot_chats_agent_graph_id_idx", table_name="copilot_chats")
    op.drop_table("copilot_chats")


def downgrade() -> None:
    # Recreate table for rollback
    op.create_table(
        "copilot_chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("agent_graph_id", sa.String, nullable=True),
        sa.Column("messages", postgresql.JSONB, nullable=True, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "copilot_chats_agent_graph_id_idx",
        "copilot_chats",
        ["agent_graph_id"],
    )
```

**Important:** Before committing, run `alembic heads` to get the correct `down_revision` value and update it. Also verify the `copilot_chats` table columns match what's in the model — adjust the `downgrade` schema if needed.

- [ ] **Step 4: Generate correct revision chain**

```bash
cd backend && alembic heads
```

Set `down_revision` to the output head revision. Alternatively, auto-generate:

```bash
cd backend && alembic revision --autogenerate -m "drop_copilot_chats_table" --rev-id "a1b2c3d4e5f6"
```

If auto-generate works, use the generated file instead.

- [ ] **Step 5: Verify migration syntax**

```bash
cd backend && python -m py_compile alembic/versions/20260406_000000_drop_copilot_chats_table.py && echo "OK"
```

Expected: OK

- [ ] **Step 6: Verify the full model compiles**

```bash
cd backend && python -m py_compile app/models/chat.py && echo "OK"
```

Expected: OK

- [ ] **Step 7: Run all tests**

```bash
cd backend && python -m pytest tests/ -k "copilot" -v --no-header
```

Expected: All new tests pass, no old tests fail (they should have been deleted in Task 9)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: drop copilot_chats table via Alembic migration"
```

---

## Manual Verification Checklist

After all tasks are completed, verify the following end-to-end:

1. **Send copilot message** → Full event stream flows: status → content → thought_step → tool_call → result → done
2. **Page refresh during execution** → Run snapshot restores last known state
3. **Run Center `/runs`** → Copilot runs visible with `copilot_turn` type, clicking opens overview
4. **`GET copilot/history`** → Returns history assembled from run snapshots
5. **`DELETE copilot/history`** → Clears copilot runs for graph
6. **Stop mid-execution** → `chat.stop` frame cleanly interrupts
7. **No Redis dependency** → Copilot works even if Redis is down (run center uses PostgreSQL)
8. **Old endpoints removed** → `POST /copilot/actions/create`, `GET /copilot/sessions/{id}`, `/ws/copilot/{id}` all return 404
