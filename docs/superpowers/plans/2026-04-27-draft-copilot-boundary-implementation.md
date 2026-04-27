# Draft Copilot Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Studio Copilot run against draft versions instead of active releases so unpublished Visual Agents can use Copilot in Build without affecting Usage-stage release behavior.

**Architecture:** Introduce a dedicated draft-aware Copilot dispatch path in the backend, keyed by `agent_version_id` rather than `release_id`, while keeping the `copilot` engine and event model unchanged. Update the frontend Graph Builder Copilot caller to send `versionId` and `workspaceId`, and lock the behavior in with API, orchestrator, and frontend tests.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async orchestration, Vitest, React hooks, Zustand stores

---

### Task 1: Add Draft Copilot API Contract Tests

**Files:**
- Create: `backend/tests/test_api/test_copilot_run.py`
- Modify: `backend/app/schemas/copilot.py`
- Modify: `backend/app/api/v1/copilot.py`
- Modify: `backend/app/services/dispatch_service.py`

- [ ] **Step 1: Write the failing API contract test for a draft-owned Copilot run**

```python
"""Contract tests for Copilot draft dispatch."""

from __future__ import annotations

import uuid
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


def _load_copilot_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/copilot.py"
    spec = importlib.util.spec_from_file_location("copilot_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


router = _load_copilot_router()


async def mock_get_current_user():
    user = MagicMock(spec=User)
    user.id = "user-123"
    user.is_superuser = False
    return user


async def mock_get_db():
    yield AsyncMock()


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(router)
    register_exception_handlers(test_app)

    from app.common.dependencies import get_current_user

    test_app.dependency_overrides[get_current_user] = mock_get_current_user
    test_app.dependency_overrides[get_db] = mock_get_db

    with TestClient(test_app) as c:
        yield c


@patch("copilot_under_test.DispatchService")
def test_copilot_run_dispatches_draft_version(
    mock_dispatch_cls,
    client: TestClient,
) -> None:
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    run = MagicMock()
    run.id = run_id
    run.current_execution_id = execution_id
    mock_dispatch_cls.return_value.dispatch_copilot_draft = AsyncMock(return_value=run)

    response = client.post(
        "/v1/copilot/run",
        json={
            "agent_id": str(agent_id),
            "version_id": str(version_id),
            "workspace_id": str(workspace_id),
            "prompt": "Add a node",
            "graph_context": {"nodes": []},
            "conversation_history": [],
            "mode": "deepagents",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {
        "run_id": str(run_id),
        "execution_id": str(execution_id),
    }
    mock_dispatch_cls.return_value.dispatch_copilot_draft.assert_awaited_once_with(
        agent_id=agent_id,
        version_id=version_id,
        workspace_id=workspace_id,
        prompt="Add a node",
        user_id="user-123",
        graph_context={"nodes": []},
        conversation_history=[],
        mode="deepagents",
        provider_name=None,
        model_name=None,
    )
```

- [ ] **Step 2: Run the new API contract test and verify it fails**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_api/test_copilot_run.py -q`

Expected: FAIL because `CopilotRunRequest` does not yet accept `version_id` and `workspace_id`, and `DispatchService` does not yet expose `dispatch_copilot_draft`.

- [ ] **Step 3: Update the Copilot request schema and route to use draft identifiers**

```python
# backend/app/schemas/copilot.py
import uuid
from typing import Any, Optional

from pydantic import BaseModel


class CopilotRunRequest(BaseModel):
    """Dispatch a Studio Copilot interaction against a draft version."""

    agent_id: uuid.UUID
    version_id: uuid.UUID
    workspace_id: uuid.UUID
    prompt: str
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]] = []
    mode: str = "deepagents"
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
```

```python
# backend/app/api/v1/copilot.py
@router.post("/run", response_model=BaseResponse[CopilotRunResponse])
async def copilot_run(
    body: CopilotRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    from app.services.dispatch_service import DispatchService

    dispatch = DispatchService(db)
    run = await dispatch.dispatch_copilot_draft(
        agent_id=body.agent_id,
        version_id=body.version_id,
        workspace_id=body.workspace_id,
        prompt=body.prompt,
        user_id=str(current_user.id),
        graph_context=body.graph_context,
        conversation_history=body.conversation_history,
        mode=body.mode,
        provider_name=body.provider_name,
        model_name=body.model_name,
    )
```

```python
# backend/app/services/dispatch_service.py
async def dispatch_copilot_draft(
    self,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    workspace_id: uuid.UUID,
    prompt: str,
    user_id: str,
    graph_context: dict,
    conversation_history: list | None = None,
    mode: str = "deepagents",
    provider_name: str | None = None,
    model_name: str | None = None,
) -> AgentRun:
    return await self._orchestrator.dispatch_copilot_draft(
        agent_id=agent_id,
        version_id=version_id,
        workspace_id=workspace_id,
        prompt=prompt,
        user_id=user_id,
        graph_context=graph_context,
        conversation_history=conversation_history,
        mode=mode,
        provider_name=provider_name,
        model_name=model_name,
    )
```

- [ ] **Step 4: Run the API contract test again and verify it passes**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_api/test_copilot_run.py -q`

Expected: PASS

- [ ] **Step 5: Commit the API contract change**

```bash
git add backend/tests/test_api/test_copilot_run.py backend/app/schemas/copilot.py backend/app/api/v1/copilot.py backend/app/services/dispatch_service.py
git commit -m "feat: route copilot requests through draft contract"
```

### Task 2: Add Orchestrator Draft Copilot Tests and Implementation

**Files:**
- Modify: `backend/app/core/engine/orchestrator.py`
- Modify: `backend/tests/test_core/test_execution_orchestrator_draft.py`

- [ ] **Step 1: Write the failing orchestrator test for draft Copilot dispatch**

```python
@pytest.mark.asyncio
async def test_dispatch_copilot_draft_uses_requested_version_without_active_release() -> None:
    db = AsyncMock()
    orchestrator = ExecutionOrchestrator(db)
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    version = MagicMock()
    version.id = version_id
    version.agent_id = agent_id
    version.definition_kind = "graph"
    version.definition_payload = {"nodes": [{"id": "n1"}], "edges": []}

    agent = MagicMock()
    agent.id = agent_id
    agent.workspace_id = workspace_id
    agent.active_release_id = None

    run = MagicMock()
    orchestrator._get_version = AsyncMock(return_value=version)  # type: ignore[method-assign]
    orchestrator._get_agent = AsyncMock(return_value=agent)  # type: ignore[method-assign]
    orchestrator._create_and_fire_draft = AsyncMock(return_value=run)  # type: ignore[attr-defined]

    result = await orchestrator.dispatch_copilot_draft(
        agent_id=agent_id,
        version_id=version_id,
        workspace_id=workspace_id,
        prompt="Add an output node",
        user_id="user-123",
        graph_context={"nodes": []},
        conversation_history=[{"role": "user", "content": "hello"}],
        mode="deepagents",
        provider_name="openai",
        model_name="gpt-5",
    )

    assert result is run
    orchestrator._create_and_fire_draft.assert_awaited_once_with(  # type: ignore[attr-defined]
        agent=agent,
        version=version,
        workspace_id=workspace_id,
        prompt="Add an output node",
        trigger_source="copilot",
        user_id="user-123",
        input_payload={
            "graph_context": {"nodes": []},
            "conversation_history": [{"role": "user", "content": "hello"}],
            "mode": "deepagents",
            "provider_name": "openai",
            "model_name": "gpt-5",
            "user_id": "user-123",
            "graph_id": str(agent_id),
        },
        engine_kind_override="copilot",
        definition_kind_override="copilot",
        definition_payload_override={
            "graph_context": {"nodes": []},
            "conversation_history": [{"role": "user", "content": "hello"}],
            "mode": "deepagents",
            "provider_name": "openai",
            "model_name": "gpt-5",
            "user_id": "user-123",
            "graph_id": str(agent_id),
        },
        executor_kind_override="copilot",
    )
```

- [ ] **Step 2: Run the orchestrator draft tests and verify the new test fails**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_orchestrator_draft.py -q`

Expected: FAIL because `dispatch_copilot_draft()` does not exist and `_create_and_fire_draft()` does not yet support engine overrides.

- [ ] **Step 3: Extend draft execution creation to support Copilot engine overrides**

```python
# backend/app/core/engine/orchestrator.py
async def dispatch_copilot_draft(
    self,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    workspace_id: uuid.UUID,
    prompt: str,
    user_id: str,
    graph_context: dict,
    conversation_history: list | None = None,
    mode: str = "deepagents",
    provider_name: str | None = None,
    model_name: str | None = None,
) -> AgentRun:
    version = await self._get_version(version_id)
    if version.agent_id != agent_id:
        raise BadRequestException("Version does not belong to this agent")

    agent = await self._get_agent(agent_id)
    if agent.workspace_id != workspace_id:
        raise BadRequestException("Agent does not belong to this workspace")

    copilot_payload = {
        "graph_context": graph_context,
        "conversation_history": conversation_history,
        "mode": mode,
        "provider_name": provider_name,
        "model_name": model_name,
        "user_id": user_id,
        "graph_id": str(agent_id),
    }

    return await self._create_and_fire_draft(
        agent=agent,
        version=version,
        workspace_id=workspace_id,
        prompt=prompt,
        trigger_source="copilot",
        user_id=user_id,
        input_payload=copilot_payload,
        engine_kind_override="copilot",
        definition_kind_override="copilot",
        definition_payload_override=copilot_payload,
        executor_kind_override="copilot",
    )
```

```python
# backend/app/core/engine/orchestrator.py
async def _create_and_fire_draft(
    self,
    agent: Agent,
    version: AgentVersion,
    workspace_id: uuid.UUID,
    prompt: str,
    trigger_source: str,
    user_id: str,
    input_payload: dict | None = None,
    *,
    engine_kind_override: str | None = None,
    definition_kind_override: str | None = None,
    definition_payload_override: dict | None = None,
    executor_kind_override: str | None = None,
) -> AgentRun:
    runtime_binding = self._build_draft_runtime_binding(version)
    engine_kind = self._resolve_draft_engine_kind(version)
    executor_kind = executor_kind_override or runtime_binding.get("runtime_type", engine_kind)

    run = AgentRun(
        release_id=None,
        agent_version_id=version.id,
        workspace_id=workspace_id,
        trigger_source=trigger_source,
        goal=prompt[:500] if prompt else None,
        input_payload=input_payload,
        status="pending",
        created_by=user_id,
    )
    ...
    execution = Execution(
        run_id=run.id,
        attempt_index=1,
        executor_kind=executor_kind,
        status="pending",
    )
    ...
    await self._fire_engine(
        execution=execution,
        release_runtime_binding=runtime_binding,
        runtime_kind=engine_kind,
        version=version,
        agent=agent,
        workspace_id=workspace_id,
        prompt=prompt,
        engine_kind_override=engine_kind_override,
        definition_kind_override=definition_kind_override,
        definition_payload_override=definition_payload_override,
    )
```

- [ ] **Step 4: Run the orchestrator draft tests again and verify they pass**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_orchestrator_draft.py -q`

Expected: PASS

- [ ] **Step 5: Commit the orchestrator refactor**

```bash
git add backend/app/core/engine/orchestrator.py backend/tests/test_core/test_execution_orchestrator_draft.py
git commit -m "feat: dispatch copilot runs against draft versions"
```

### Task 3: Add API Regression Tests for Release Boundary Preservation

**Files:**
- Modify: `backend/tests/test_api/test_copilot_run.py`

- [ ] **Step 1: Add failing tests for run ownership and draft validation errors**

```python
@patch("copilot_under_test.DispatchService")
def test_copilot_run_returns_draft_owned_execution(
    mock_dispatch_cls,
    client: TestClient,
) -> None:
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()
    run.current_execution_id = uuid.uuid4()
    run.release_id = None
    run.agent_version_id = version_id
    mock_dispatch_cls.return_value.dispatch_copilot_draft = AsyncMock(return_value=run)

    response = client.post(
        "/v1/copilot/run",
        json={
            "agent_id": str(agent_id),
            "version_id": str(version_id),
            "workspace_id": str(workspace_id),
            "prompt": "Explain this graph",
            "graph_context": {"nodes": []},
            "conversation_history": [],
        },
    )

    assert response.status_code == 200
    mock_dispatch_cls.return_value.dispatch_copilot_draft.assert_awaited_once()
```

```python
@patch("copilot_under_test.DispatchService")
def test_copilot_run_requires_draft_identifiers(
    mock_dispatch_cls,
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/copilot/run",
        json={
            "agent_id": str(uuid.uuid4()),
            "prompt": "Explain this graph",
            "graph_context": {"nodes": []},
            "conversation_history": [],
        },
    )

    assert response.status_code == 422
    mock_dispatch_cls.return_value.dispatch_copilot_draft.assert_not_called()
```

- [ ] **Step 2: Run the Copilot API tests and verify failures are limited to the new assertions**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_api/test_copilot_run.py -q`

Expected: FAIL only until route/schema changes from Tasks 1-2 are present; PASS after those changes are applied.

- [ ] **Step 3: Keep the route draft-only and do not reintroduce active release fallback**

```python
# backend/app/api/v1/copilot.py
"""
Studio Copilot runs against draft versions only.
Do not read agent.active_release_id here.
Usage-stage chat and business runs keep their own release-based paths.
"""
```

- [ ] **Step 4: Run the focused backend API suite to verify no draft endpoint regressions**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_api/test_copilot_run.py backend/tests/test_api/test_agent_runs_draft.py -q`

Expected: PASS

- [ ] **Step 5: Commit the API regression coverage**

```bash
git add backend/tests/test_api/test_copilot_run.py backend/app/api/v1/copilot.py
git commit -m "test: lock copilot to draft-only api contract"
```

### Task 4: Add Frontend Copilot Request Tests and Implementation

**Files:**
- Modify: `frontend/services/copilotService.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
- Create: `frontend/services/__tests__/copilotService.test.ts`

- [ ] **Step 1: Write the failing frontend service test for draft identifiers**

```typescript
import { describe, expect, it, vi } from 'vitest'

const apiPost = vi.fn()

vi.mock('@/lib/api-client', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
}))

import { copilotService } from '../copilotService'

describe('copilotService.dispatchRun', () => {
  it('sends draft identifiers with the copilot run request', async () => {
    apiPost.mockResolvedValue({ run_id: 'run-1', execution_id: 'exec-1' })

    await copilotService.dispatchRun({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      prompt: 'Add a node',
      graphContext: { nodes: [] },
      conversationHistory: [],
      mode: 'deepagents',
    })

    expect(apiPost).toHaveBeenCalledWith('copilot/run', {
      agent_id: 'agent-1',
      version_id: 'version-1',
      workspace_id: 'workspace-1',
      prompt: 'Add a node',
      graph_context: { nodes: [] },
      conversation_history: [],
      mode: 'deepagents',
      provider_name: undefined,
      model_name: undefined,
    })
  })
})
```

- [ ] **Step 2: Run the frontend service test and verify it fails**

Run: `PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm vitest frontend/services/__tests__/copilotService.test.ts --run`

Expected: FAIL because `dispatchRun()` does not yet accept `versionId` and `workspaceId`.

- [ ] **Step 3: Update the service contract to send draft identifiers**

```typescript
// frontend/services/copilotService.ts
async dispatchRun(params: {
  agentId: string
  versionId: string
  workspaceId: string
  prompt: string
  graphContext: Record<string, unknown>
  conversationHistory: Array<{ role: 'user' | 'model'; text: string; actions?: GraphAction[] }>
  mode?: string
  providerName?: string
  modelName?: string
}): Promise<{ run_id: string; execution_id: string }> {
  return apiPost<{ run_id: string; execution_id: string }>('copilot/run', {
    agent_id: params.agentId,
    version_id: params.versionId,
    workspace_id: params.workspaceId,
    prompt: params.prompt,
    graph_context: params.graphContext,
    conversation_history: convertConversationHistory(params.conversationHistory),
    mode: params.mode || 'deepagents',
    provider_name: params.providerName,
    model_name: params.modelName,
  })
}
```

- [ ] **Step 4: Run the frontend service test again and verify it passes**

Run: `PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm vitest frontend/services/__tests__/copilotService.test.ts --run`

Expected: PASS

- [ ] **Step 5: Commit the frontend service contract change**

```bash
git add frontend/services/copilotService.ts frontend/services/__tests__/copilotService.test.ts
git commit -m "feat: send draft identifiers with copilot requests"
```

### Task 5: Add Graph Builder Hook Boundary Tests and Implementation

**Files:**
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`
- Create: `frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts`

- [ ] **Step 1: Write the failing hook test for draft-aware Build dispatch**

```typescript
import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const dispatchRun = vi.fn()

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

vi.mock('@/services/agentRunService', () => ({
  agentRunService: {
    sendMessage: vi.fn(),
    cancel: vi.fn(),
  },
}))

vi.mock('@/services/copilotService', () => ({
  copilotService: {
    dispatchRun: (...args: unknown[]) => dispatchRun(...args),
  },
}))

vi.mock('../stores/graphStore', () => ({
  useGraphStore: {
    getState: () => ({
      graphId: 'graph-1',
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
    }),
  },
}))

import { useCopilotActions } from '../useCopilotActions'

describe('useCopilotActions', () => {
  it('dispatches the first copilot message against the draft version', async () => {
    dispatchRun.mockResolvedValue({ run_id: 'run-1', execution_id: 'exec-1' })

    const actions = {
      setInput: vi.fn(),
      addMessage: vi.fn(),
      setLoading: vi.fn(),
      clearStreaming: vi.fn(),
      clearSession: vi.fn(),
      setCurrentStage: vi.fn(),
      setThinkingMessage: vi.fn(),
      setSession: vi.fn(),
      finalizeCurrentMessage: vi.fn(),
      removeCurrentMessage: vi.fn(),
      clearMessages: vi.fn(),
      clearExpandedItems: vi.fn(),
    }

    const refs = {
      isMountedRef: { current: true },
      isCreatingSessionRef: { current: false },
      hasProcessedUrlInputRef: { current: false },
    }

    const { result } = renderHook(() =>
      useCopilotActions({
        state: {
          input: '',
          messages: [],
          loading: false,
          currentExecutionId: null,
          currentRunId: null,
        } as any,
        actions: actions as any,
        refs: refs as any,
      }),
    )

    await act(async () => {
      await result.current.handleSendWithInput('Add a node')
    })

    expect(dispatchRun).toHaveBeenCalledWith({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      prompt: 'Add a node',
      graphContext: expect.any(Object),
      conversationHistory: [],
      mode: 'deepagents',
      providerName: undefined,
      modelName: undefined,
    })
  })
})
```

- [ ] **Step 2: Run the hook test and verify it fails**

Run: `PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm vitest frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts --run`

Expected: FAIL because the hook currently reads only `graphId` and `agentId`.

- [ ] **Step 3: Update the Graph Builder hook to require draft identifiers for the first message**

```typescript
// frontend/components/editors/graph-builder/hooks/useCopilotActions.ts
const storeState = useGraphStore.getState()
const storeGraphId = storeState.graphId
const storeAgentId = storeState.agentId
const storeVersionId = storeState.versionId
const storeWorkspaceId = storeState.workspaceId

if (!storeGraphId || !storeAgentId || !storeVersionId || !storeWorkspaceId) {
  console.error('[CopilotPanel] Missing graph, agent, version, or workspace in store')
  if (refs.isMountedRef.current) {
    actions.setLoading(false)
    actions.finalizeCurrentMessage(
      `${t('workspace.systemError')}: ${t('workspace.couldNotProcessRequest')}`,
    )
  }
  return
}

const { run_id, execution_id } = await copilotService.dispatchRun({
  agentId: storeAgentId,
  versionId: storeVersionId,
  workspaceId: storeWorkspaceId,
  prompt: userText,
  graphContext,
  conversationHistory: state.messages,
  mode: copilotMode,
  providerName: selectedProviderName,
  modelName: selectedModelName,
})
```

- [ ] **Step 4: Run the hook test and the existing draft execution test suite**

Run: `PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm vitest frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts frontend/components/editors/graph-builder/stores/execution/__tests__/executionStore.draft.test.ts frontend/components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx --run`

Expected: PASS

- [ ] **Step 5: Commit the Graph Builder Copilot boundary update**

```bash
git add frontend/components/editors/graph-builder/hooks/useCopilotActions.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts
git commit -m "feat: bind builder copilot to draft context"
```

### Task 6: Full Verification and Cleanup

**Files:**
- Modify: `backend/app/api/v1/copilot.py`
- Modify: `backend/app/core/engine/orchestrator.py`
- Modify: `frontend/services/copilotService.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotActions.ts`

- [ ] **Step 1: Run the focused backend verification suite**

Run: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_execution_orchestrator_draft.py backend/tests/test_api/test_copilot_run.py backend/tests/test_api/test_agent_runs_draft.py backend/tests/test_api/test_executions_message.py -q`

Expected: PASS

- [ ] **Step 2: Run the focused frontend verification suite**

Run: `PATH=/Users/yuzhenjiang1/.nvm/versions/node/v22.17.0/bin:$PATH pnpm vitest frontend/services/__tests__/copilotService.test.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts frontend/components/editors/graph-builder/stores/execution/__tests__/executionStore.draft.test.ts frontend/components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx --run`

Expected: PASS

- [ ] **Step 3: Verify the implementation against the spec boundary**

```text
Confirm all of the following in code review:
- /v1/copilot/run does not read active_release_id
- Copilot draft runs store agent_version_id and release_id=None
- Usage-stage release-based paths remain unchanged
- Build-stage callers always provide versionId and workspaceId
```

- [ ] **Step 4: Stage the final implementation set**

```bash
git add backend/app/schemas/copilot.py backend/app/api/v1/copilot.py backend/app/services/dispatch_service.py backend/app/core/engine/orchestrator.py backend/tests/test_api/test_copilot_run.py backend/tests/test_core/test_execution_orchestrator_draft.py frontend/services/copilotService.ts frontend/services/__tests__/copilotService.test.ts frontend/components/editors/graph-builder/hooks/useCopilotActions.ts frontend/components/editors/graph-builder/hooks/__tests__/useCopilotActions.test.ts
```

- [ ] **Step 5: Commit the completed feature**

```bash
git commit -m "feat: run studio copilot against draft versions"
```
