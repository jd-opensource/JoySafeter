# WS2: Backend Entry Layer Unification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all execution through `ExecutionOrchestrator`, add the missing `POST /v1/executions/{id}/message` endpoint, and delete the old WS handlers that are broken or deprecated.

**Architecture:** The Orchestrator (already implemented) is the single entry point. The old `ChatWsHandler` → `ChatTurnExecutor` pipeline has two `raise RuntimeError` paths (GraphService removed). Rather than fixing them, we delete them and route everything through the Orchestrator. The copilot turn path is preserved separately as it's still functional.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, pytest

**Test framework:** pytest with `asyncio_mode = "auto"`. Existing test patterns in `backend/tests/test_api/` (mocked DB, FastAPI TestClient) and `backend/tests/test_core/`.

---

### Task 1: Add `POST /v1/executions/{id}/message` endpoint

This endpoint is required by Workstream 1's `executionAdapter.injectMessage()`. The `Orchestrator.send_message()` method already exists (line 198 of `orchestrator.py`).

**Files:**
- Modify: `backend/app/api/v1/executions.py:79-96` (add new route after existing ones)
- Create: `backend/tests/test_api/test_executions_message.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_api/test_executions_message.py
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_inject_message_calls_orchestrator(app_client: AsyncClient):
    execution_id = uuid.uuid4()
    with patch('app.api.v1.executions.ExecutionOrchestrator') as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.send_message = AsyncMock()

        response = await app_client.post(
            f"/api/v1/executions/{execution_id}/message",
            json={"message": "continue"},
        )

        assert response.status_code == 200
        mock_instance.send_message.assert_called_once_with(execution_id, "continue")


@pytest.mark.asyncio
async def test_inject_message_empty_body_returns_422(app_client: AsyncClient):
    execution_id = uuid.uuid4()
    response = await app_client.post(
        f"/api/v1/executions/{execution_id}/message",
        json={},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api/test_executions_message.py -v`
Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/v1/executions.py`, add after line 95:

```python
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.schemas.task import InjectMessageRequest


@router.post("/{execution_id}/message", response_model=BaseResponse)
async def inject_message(
    execution_id: UUID,
    body: InjectMessageRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    orchestrator = ExecutionOrchestrator(db)
    await orchestrator.send_message(execution_id, body.message)
    return BaseResponse(data={"status": "sent"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api/test_executions_message.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/executions.py backend/tests/test_api/test_executions_message.py
git commit -m "feat(api): add POST /v1/executions/{id}/message for runtime message injection"
```

---

### Task 2: Preserve copilot turn path before deleting old handlers

The `CopilotService._get_copilot_stream()` (called from `ChatTurnExecutor.execute_copilot_turn`, line 746) is the only functional execution path in the old handler. Before deleting the old WS handler, ensure the copilot path is accessible through the Orchestrator or a standalone service.

**Files:**
- Read: `backend/app/services/copilot_service.py:86-133` (`_get_copilot_stream`)
- Read: `backend/app/websocket/chat_turn_executor.py:746-966` (`execute_copilot_turn`)

- [ ] **Step 1: Analyze copilot execution flow**

The copilot turn:
1. `ChatTurnExecutor.execute_copilot_turn` receives `CopilotTurnCommand`
2. Calls `CopilotService._get_copilot_stream(graph_context, conversation_history, mode)`
3. Iterates stream events, emits them via WS
4. Calls `_persist_graph_from_actions` (currently a no-op stub)

Since copilot actions modify graph state (not run execution), this is NOT an `ExecutionOrchestrator` concern. The copilot is a graph-editing assistant, not a graph-executing engine.

- [ ] **Step 2: Decide on copilot path**

The copilot stream is consumed from the old `/ws/chat` endpoint. Two options:
- **Option A:** Keep the copilot frame handling in a new, slim `copilot_ws_handler.py`
- **Option B:** Move copilot to an HTTP SSE endpoint (`POST /v1/copilot/stream`)

Choose based on codebase patterns. The copilot is edit-time, not runtime — an HTTP SSE endpoint is simpler and doesn't need persistent WS connection.

- [ ] **Step 3: Extract copilot to standalone service endpoint**

Create `backend/app/api/v1/copilot.py`:

```python
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.services.copilot_service import CopilotService
from app.common.dependencies import get_current_user, get_db

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])

@router.post("/stream")
async def copilot_stream(
    body: CopilotStreamRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    service = CopilotService(
        user_id=str(current_user.id),
        provider_name=body.provider_name,
        model_name=body.model_name,
        db=db,
    )
    stream = service._get_copilot_stream(
        graph_context=body.graph_context,
        conversation_history=body.conversation_history,
        mode=body.mode,
    )

    async def event_generator():
        async for event in stream:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Create `CopilotStreamRequest` schema in `backend/app/schemas/copilot.py`:

```python
from pydantic import BaseModel
from typing import Optional

class CopilotStreamRequest(BaseModel):
    provider_name: str
    model_name: str
    graph_context: dict
    conversation_history: list
    mode: Optional[str] = None
```

Register router in `app/api/v1/__init__.py`.

- [ ] **Step 4: Run existing copilot tests**

Run: `cd backend && python -m pytest tests/test_api/test_chat_commands_copilot.py tests/test_api/test_copilot_event_mirroring.py tests/test_api/test_copilot_history_from_runs.py -v`
Expected: Existing tests still pass (they test data structures, not the endpoint).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/copilot.py
git commit -m "feat(api): extract copilot stream to standalone SSE endpoint"
```

---

### Task 3: Delete old WS handlers + update `main.py`

With copilot extracted and all execution going through `/ws/executions`, the old handlers are dead code.

**Files:**
- Delete: `backend/app/websocket/chat_ws_handler.py` (604 lines)
- Delete: `backend/app/websocket/chat_turn_executor.py` (977 lines)
- Delete: `backend/app/websocket/chat_task_supervisor.py` (203 lines)
- Delete: `backend/app/websocket/chat_commands.py` (135 lines)
- Delete: `backend/app/websocket/chat_protocol.py` (198 lines)
- Delete: `backend/app/websocket/run_subscription_handler.py` (84 lines — already returns deprecation error)
- Modify: `backend/app/main.py:324-386` (remove `/ws/chat` and `/ws/runs` route registrations)

- [ ] **Step 1: Remove WS route registrations from `main.py`**

In `main.py`, remove:
- Lines 324-334: `/ws/chat` route handler
- Lines 377-386: `/ws/runs` route handler
- Related imports at top of file

Keep: `/ws/executions` (line 389), `/ws/notifications` (line 368), `/ws/openclaw/*` routes.

- [ ] **Step 2: Delete the 6 old handler files**

```bash
rm backend/app/websocket/chat_ws_handler.py
rm backend/app/websocket/chat_turn_executor.py
rm backend/app/websocket/chat_task_supervisor.py
rm backend/app/websocket/chat_commands.py
rm backend/app/websocket/chat_protocol.py
rm backend/app/websocket/run_subscription_handler.py
```

- [ ] **Step 3: Check for remaining imports of deleted modules**

Run: `cd backend && grep -r "chat_ws_handler\|chat_turn_executor\|chat_task_supervisor\|chat_commands\|chat_protocol\|run_subscription_handler" --include="*.py" -l`

Fix any imports found (likely only `main.py` which was already updated).

- [ ] **Step 4: Update or delete tests for removed handlers**

The following test files test deleted code:
- `backend/tests/test_api/test_chat_ws_handler.py` — delete
- `backend/tests/test_api/test_chat_commands_chat_run.py` — delete
- `backend/tests/test_api/test_chat_protocol.py` — delete
- `backend/tests/test_api/test_chat_protocol_chat_extension.py` — delete
- `backend/tests/test_api/test_chat_protocol_copilot_extension.py` — keep if copilot protocol types are preserved, else delete

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest -x --timeout=30 2>&1 | tail -20`
Expected: All remaining tests pass.

- [ ] **Step 6: Commit**

```bash
git add -u backend/
git commit -m "refactor(backend): delete old WS chat handlers and run subscription handler

All execution now flows through ExecutionOrchestrator via /ws/executions.
Copilot extracted to standalone SSE endpoint."
```

---

### Task 4: Simplify `session_service.py`

The session service wraps `thread_id` logic with a `Message`-based "session" concept. With threads now first-class via `ThreadService`, simplify or remove.

**Files:**
- Read: `backend/app/services/session_service.py` (175 lines)
- Read: `backend/app/api/v1/sessions.py` (find callers)
- Modify or Delete: `backend/app/services/session_service.py`

- [ ] **Step 1: Audit callers of `SessionService`**

Run: `cd backend && grep -r "SessionService\|session_service" --include="*.py" -l`

Identify all callers. The session service is used by `api/v1/sessions.py` for the sessions HTTP API.

- [ ] **Step 2: Determine strategy**

If `sessions.py` is the only caller and the sessions API is used by the frontend's old chat interface (which we're removing), mark `session_service.py` + `sessions.py` for deletion.

If sessions API is still used by the frontend for thread management, make `SessionService` a thin wrapper around `ThreadService`.

- [ ] **Step 3: Implement chosen strategy**

Either delete both files or simplify to:
```python
class SessionService:
    def __init__(self, db):
        self.thread_service = ThreadService(db)

    async def create_session(self, data, user_id):
        return await self.thread_service.create_thread(data.agent_id, user_id)

    async def get_session(self, session_id):
        return await self.thread_service.get_thread(session_id)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest -x --timeout=30 2>&1 | tail -20`
Expected: Pass.

- [ ] **Step 5: Commit**

```bash
git add -u backend/
git commit -m "refactor(backend): simplify session_service to thin ThreadService wrapper"
```

---

### Task 5: Fix `chat.py` utility functions

`chat.py` (504 lines) is NOT a router — it's a shared utility library. With the old WS handlers deleted, audit which functions are still called.

**Files:**
- Modify: `backend/app/api/v1/chat.py`

- [ ] **Step 1: Audit remaining callers**

Run: `cd backend && grep -r "from app.api.v1.chat import\|from app.api.v1 import chat" --include="*.py"`

With `chat_ws_handler.py` and `chat_turn_executor.py` deleted, many imports may now be dead.

- [ ] **Step 2: Remove dead functions**

Functions likely dead after handler deletion:
- `_dispatch_stream_event` — only called from `ChatTurnExecutor`
- `get_or_create_conversation` — only called from `ChatWsHandler`
- `_clear_interrupt_marker` — no-op stub
- `_enrich_message` — only called from `ChatWsHandler._handle_chat_start_frame`
- `safe_get_state` — may be used by copilot service (verify)
- `save_run_result` — may be used by copilot service (verify)
- `save_user_message` / `save_assistant_message` — may be used elsewhere (verify)

Keep any functions still imported.

- [ ] **Step 3: If all functions are dead, delete `chat.py` entirely**

If no remaining callers exist after the cleanup, delete the file.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest -x --timeout=30 2>&1 | tail -20`
Expected: Pass.

- [ ] **Step 5: Commit**

```bash
git add -u backend/
git commit -m "chore(backend): remove dead functions from chat.py utility module"
```

---

### Task 6: Fix `node_secrets.py` broken stubs + verify `node_tools.py`

**Actual paths:**
- `backend/app/core/graph/node_secrets.py` (116 lines, in `core/graph/`)
- `backend/app/core/agent/node_tools.py` (470 lines, in `core/agent/`)

**Note:** The spec (Step 2.4) incorrectly states both are in `core/agent/`. `node_secrets.py` is in `core/graph/`, `node_tools.py` is in `core/agent/`.

The `store_a2a_auth_headers` function raises `RuntimeError`. The `resolve_a2a_auth_headers` returns `None`. The module docstring says secrets should now be stored inline in `definition_payload`.

`node_tools.py` duck-types node objects (`node.data.config.tools`) — no ORM imports. Verify it works with `definition_payload` node objects.

**Files:**
- Modify: `backend/app/core/graph/node_secrets.py`
- Verify: `backend/app/core/agent/node_tools.py`

- [ ] **Step 1: Audit callers of broken functions**

Run: `cd backend && grep -r "store_a2a_auth_headers\|resolve_a2a_auth_headers" --include="*.py" -l`

- [ ] **Step 1b: Verify `node_tools.py` works with definition_payload objects**

`node_tools.py` (`core/agent/node_tools.py`) duck-types node objects: `node.data.config.tools` (line 47). Verify that when nodes are passed from `definition_payload` (plain dicts), the attribute access still works. If `definition_payload` stores nodes as dicts, `node_tools.py` may need to use `node["data"]["config"]["tools"]` instead of attribute access. Check and fix if needed.

Run: `cd backend && grep -n "node\.data" app/core/agent/node_tools.py | head -10`

- [ ] **Step 2: Update callers to use `definition_payload` inline secrets**

The `hydrate_nodes_a2a_secrets` function (line 88) already works with duck-typed objects — it resolves `__secretRef` markers in node data. Ensure it reads from the `definition_payload` context rather than a DB table.

If `store_a2a_auth_headers` has callers, replace them with inline storage into `definition_payload["node_secrets"]` and update `hydrate_nodes_a2a_secrets` to read from there.

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest -x --timeout=30 2>&1 | tail -20`
Expected: Pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/graph/node_secrets.py
git commit -m "fix(graph-engine): migrate node_secrets to definition_payload inline storage"
```

---

### Task 7: Fix `copilot_service._persist_graph_from_actions` stub

**Files:**
- Modify: `backend/app/services/copilot_service.py:529-540`

- [ ] **Step 1: Implement graph persistence via `agentVersionService`**

The stub at line 529 needs to persist copilot-generated graph changes. Replace with:

```python
async def _persist_graph_from_actions(self, actions: list, graph_id: str) -> bool:
    """Persist copilot graph changes to the agent's draft version."""
    try:
        # Resolve agent + draft version from graph context
        # Update definition_payload with new nodes/edges from actions
        # Call agentVersionService equivalent
        agent = await self.db.execute(
            select(Agent).where(Agent.id == uuid.UUID(graph_id))
        )
        agent = agent.scalar_one_or_none()
        if not agent or not agent.current_draft_version_id:
            logger.warning(f"Cannot persist: no draft version for agent {graph_id}")
            return False

        version = await self.db.execute(
            select(AgentVersion).where(AgentVersion.id == agent.current_draft_version_id)
        )
        version = version.scalar_one()
        payload = dict(version.definition_payload or {})
        # Apply actions to payload (nodes/edges modifications)
        # ... action-specific logic ...
        version.definition_payload = payload
        await self.db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to persist graph from actions: {e}")
        return False
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/test_api/test_copilot_event_mirroring.py -v`
Expected: Pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/copilot_service.py
git commit -m "fix(copilot): implement graph persistence via AgentVersion.definition_payload"
```

---

### Task 8: Cleanup `__pycache__` and verify

**Files:**
- Delete: stale `.pyc` files for deleted modules

- [ ] **Step 1: Clean pycache**

```bash
find backend/ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
find backend/ -name "*.pyc" -delete 2>/dev/null
```

- [ ] **Step 2: Run full test suite**

Run: `cd backend && python -m pytest -x --timeout=60 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 3: Run type check if mypy is configured**

Run: `cd backend && python -m mypy app/ --ignore-missing-imports 2>&1 | tail -20` (if mypy is available)

- [ ] **Step 4: Commit**

```bash
git add -u backend/
git commit -m "chore(backend): clean up pycache and verify full test suite"
```
