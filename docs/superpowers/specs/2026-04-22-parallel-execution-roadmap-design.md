# Parallel Execution Roadmap: Graph Builder + Execution Engine + Product Form

**Date**: 2026-04-22
**Status**: Approved
**Strategy**: Strategy A — 按层并行, 3 条独立线同时推进, 随做随清

## Context

Three design documents define the full-stack migration:

1. **`2026-04-22-graph-builder-integration-design.md`** — 3 frontend adapters bridging Graph Builder to new domain APIs
2. **`2026-04-22-frontend-product-form-design.md`** — conceptual model (Agent/Version/Release/Task/Run), routes, permissions
3. **`2026-04-22-unified-execution-engine-design.md`** — 6-layer execution architecture with unified Orchestrator

### Current Completion (~60%)

**Done:**
- Backend engine abstraction: `protocol.py`, `registry.py`, `cli_engine.py`, `graph_engine.py`
- `ExecutionOrchestrator` with `dispatch_task/chat/direct`, `cancel`, `retry`, `_sync_task_status`
- All new domain models: `Agent`, `AgentVersion`, `AgentRelease`, `Task`, `AgentRun`, `Execution`, `ExecutionEvent`, `Thread`
- New API routes + services: `agents`, `agent_runs`, `tasks`, `threads`, `executions`, `artifacts`
- Execution WS: `execution_subscription_handler.py` + manager registered in `main.py`
- Graph Builder 84 files migrated to `components/editors/graph-builder/`
- Shared UI extracted: `artifact-panel`, `code-viewer`, `tool-call-display`, `useCopyToClipboard`, `types/chat`
- Most import path fixes complete
- `deploymentAdapter.ts` (Adapter 2) fully implemented
- Route page scaffolds for `/agents/[id]/edit|versions|releases|tasks|threads|runs`

**Not Done (~40%):** See the three workstreams below.

### Key Decisions

| Decision | Choice |
|---|---|
| Execution strategy | All 3 lines in parallel, single developer + multi-Agent |
| Legacy cleanup | 随做随清 (clean up immediately after each replacement) |
| TaskStatus enum | Keep current 6 values: `backlog, todo, in_progress, in_review, done, cancelled` |

---

## Workstream 1: Frontend Adapter Layer

**Goal**: Graph Builder can save/load, deploy, run, and view deployment history end-to-end.

**Scope**: `frontend/components/editors/graph-builder/` + `frontend/app/agents/[agentId]/edit/`

### Step 1.1 — Create `graphDataAdapter.ts`

New file: `frontend/components/editors/graph-builder/services/graphDataAdapter.ts`

Bridge `builderStore.loadGraph()`/`saveGraph()` to `agentVersionService`:

```typescript
export const graphDataAdapter = {
  async load(agentId: string, versionId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId)
    return version.definition_payload as GraphState
  },

  async save(agentId: string, versionId: string, graphState: GraphState): Promise<void> {
    await agentVersionService.update(agentId, versionId, {
      definition_payload: graphState,
    })
  },

  async createDraft(agentId: string, workspaceId: string, basePayload?: object): Promise<string> {
    const version = await agentVersionService.create(agentId, workspaceId, {
      definition_kind: 'graph',
      definition_payload: basePayload || {},
    })
    return version.id
  },
}
```

Update `saveManager.ts` and `builderStore.loadGraph()` to call `graphDataAdapter` instead of the old `agentService.saveGraphState()`.

### Step 1.2 — Create `executionAdapter.ts`

New file: `frontend/components/editors/graph-builder/services/executionAdapter.ts`

Bridge `RunInputModal` to `POST /v1/runs` + execution WS:

```typescript
export const executionAdapter = {
  async startRun(releaseId: string, prompt: string, workspaceId: string): Promise<RunResult> {
    const response = await fetch('/api/v1/runs', {
      method: 'POST',
      body: JSON.stringify({ release_id: releaseId, prompt, workspace_id: workspaceId }),
    })
    return response.json()  // { run_id, execution_id }
  },

  subscribeToExecution(executionId: string): WebSocket {
    const ws = new WebSocket(`${WS_BASE}/ws/executions`)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe', execution_id: executionId }))
    }
    return ws
  },

  async cancelRun(runId: string): Promise<void> {
    await fetch(`/api/v1/runs/${runId}/cancel`, { method: 'POST' })
  },

  async injectMessage(executionId: string, message: string): Promise<void> {
    await fetch(`/api/v1/executions/${executionId}/message`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    })
  },
}
```

`RunInputModal` submit calls `startRun()`, gets `execution_id`, calls `subscribeToExecution()`. `ExecutionStore` consumes the WS event stream.

### Step 1.3 — Fix `BuilderToolbar.handleDeploy`

Current L97-128 is a stub (comment says "simplified deployment approach"). Replace with:

1. Get current draft `versionId` from `builderStore`
2. Call `deploymentAdapter.deploy(agentId, versionId, workspaceId)`
3. Invalidate query cache (already present)
4. Show toast on success/failure (already present)

### Step 1.4 — Fix `useDeploymentHistory.ts`

Current operations all `throw new Error('has been removed')`. Replace:

- List loading → `deploymentAdapter.list(agentId, workspaceId)`
- Revert → `deploymentAdapter.activate(agentId, releaseId, workspaceId)`
- Delete/Undeploy → `deploymentAdapter.retire(agentId, releaseId, workspaceId)`
- Remove stubbed `graphDeploymentService` and `deploymentStore` references

### Step 1.5 — Agent edit page integration

`/agents/[agentId]/edit/page.tsx`:

```tsx
if (agent.definition_kind === 'graph') {
  return <AgentBuilder agentId={agentId} workspaceId={workspaceId} />
}
// else: render prompt editor (existing)
```

### Cleanup (随做随清)

- Remove old `graphs/{id}/state` endpoint calls from `hooks/queries/graphs.ts`
- Remove dead `loadGraph/saveGraph` paths in `builderStore` once adapter is wired

---

## Workstream 2: Backend Entry Layer Unification

**Goal**: All execution flows go through `ExecutionOrchestrator`. Delete old WS handlers and fix Graph Engine internals.

**Scope**: `backend/app/api/v1/`, `backend/app/websocket/`, `backend/app/services/`, `backend/app/core/graph/`

### Step 2.1 — Simplify `chat.py` API

Replace direct `session_service` → `chat_turn_executor` chain with:

```python
@router.post("/{thread_id}/message")
async def send_message(thread_id: UUID, body: SendMessageRequest, user=Depends(get_current_user), db=Depends(get_db)):
    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_chat(thread_id, body.message, user.id)
    return {"run_id": str(run.id), "execution_id": str(run.current_execution_id)}
```

### Step 2.2 — Simplify `session_service.py`

Convert to thin wrapper around `ThreadService`, or delete entirely if no other callers:
- `create_session()` → `thread_service.create_thread()`
- `get_session()` → `thread_service.get_thread()`
- All execution logic removed (Orchestrator handles it)

### Step 2.3 — Delete old WS handlers

Files to delete (execution_subscription_handler.py is the replacement, already registered):
- `chat_ws_handler.py`
- `run_subscription_handler.py`
- `chat_turn_executor.py`
- `chat_task_supervisor.py`
- `chat_commands.py`
- `chat_protocol.py`

Remove their route registrations from `main.py`.

### Step 2.4 — Fix `node_secrets.py` + `node_tools.py`

Current: read from old `graphs` table (`graph.nodes[node_id].config`).
New: read from `AgentVersion.definition_payload["nodes"][node_id]["config"]`.

The `GraphEngine.start()` already receives `definition_payload` as a parameter — thread it through to node execution functions.

### Step 2.5 — Fix `copilot_service.py`

Update imports from old models (`graph_execution`, `graph_deployment_version`) to new models (`Execution`, `AgentRelease`).

### Cleanup (随做随清)

Delete each old file immediately after its replacement is confirmed working. Clean up `__pycache__/*.pyc` for deleted modules.

---

## Workstream 3: Data Layer + Permissions

**Goal**: TaskStatus DB consistency, workspace permissions, Run/Task page wiring, legacy route deletion.

**Scope**: `backend/alembic/`, `frontend/hooks/`, `frontend/app/runs/`, `frontend/app/tasks/`, `frontend/app/workspace/` (delete)

### Step 3.1 — TaskStatus alembic migration

Create new migration to ensure DB enum matches the 6-value model:

```python
def upgrade():
    # Add new values if enum exists with fewer values
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'todo'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'in_review'")

def downgrade():
    pass  # PostgreSQL cannot remove enum values
```

Verify `orchestrator.py` L421 `run.failed → task.status = "in_review"` matches the enum (currently correct).

### Step 3.2 — Create `useWorkspacePermission` hook

New file: `frontend/hooks/useWorkspacePermission.ts`

```typescript
type WorkspaceRole = 'viewer' | 'member' | 'admin' | 'owner'

interface PermissionCheck {
  role: WorkspaceRole
  canEdit: boolean           // member+
  canDeploy: boolean         // admin+
  canManageMembers: boolean  // admin+
  canDelete: boolean         // owner only
  isLoading: boolean
}

export function useWorkspacePermission(workspaceId: string): PermissionCheck
```

Read current user's role from workspace membership API. Consumed by `BuilderToolbar`, `DeploymentHistoryPanel`, Task dispatch buttons.

### Step 3.3 — Run detail page wiring

`/runs/[runId]/page.tsx`:
1. Query `AgentRun` by `runId` → get `current_execution_id`
2. Connect to `/ws/executions/{executionId}` for live events
3. Render `ExecutionTimeline` + `ExecutionDetailPanel` (already exported from `components/execution/`)

### Step 3.4 — Task page auto-sync display

`/tasks/` and `/agents/[agentId]/tasks/`:
- Task cards show `latest_run_id` linked run status
- Status transitions (`in_progress → done / in_review`) update via WS notification or polling
- Task dispatch button calls `POST /v1/tasks/{id}/dispatch` (API exists)

### Step 3.5 — Delete legacy routes

| Delete | Replaced by |
|---|---|
| `frontend/app/workspace/` (entire directory) | `/agents/[agentId]/edit` |
| `frontend/app/discover/` (if exists) | `/agents` list page |
| Old endpoint calls in `hooks/queries/graphs.ts` | `graphDataAdapter` |

Verify no remaining imports reference these paths before deletion.

---

## File Conflict Analysis

The three workstreams touch non-overlapping file sets:

| Workstream | Files touched |
|---|---|
| **1 (Frontend Adapter)** | `frontend/components/editors/graph-builder/**`, `frontend/app/agents/**/edit/` |
| **2 (Backend Entry)** | `backend/app/api/v1/chat.py`, `backend/app/services/session_service.py`, `backend/app/websocket/chat_*`, `backend/app/core/graph/node_*` |
| **3 (Data + Permissions)** | `backend/alembic/`, `frontend/hooks/useWorkspacePermission.ts`, `frontend/app/runs/`, `frontend/app/tasks/`, `frontend/app/workspace/` (delete) |

**Single intersection**: Workstream 1's `executionAdapter` connects to the WS endpoint maintained by Workstream 2. The endpoint (`/ws/executions/{id}`) is already live and API-stable — no blocking dependency.

## Integration Verification

After all 3 workstreams complete:
1. Build verification: `npm run build` (frontend) + `pytest` (backend)
2. E2E flow: Create agent → Edit graph → Save → Deploy → Run → View execution → Check task status sync
3. Verify no references to deleted files remain
4. Verify no old route paths (`/workspace`, `/discover`) are reachable
