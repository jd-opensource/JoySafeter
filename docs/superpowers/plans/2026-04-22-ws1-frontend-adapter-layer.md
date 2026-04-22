# WS1: Frontend Adapter Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Graph Builder to the new domain model so it can save/load graphs via `AgentVersion.definition_payload`, deploy via `AgentRelease`, and run via `POST /v1/runs` + `/ws/executions`.

**Architecture:** Three adapter services (`graphDataAdapter`, `executionAdapter`, existing `deploymentAdapter`) sit between Graph Builder internal stores and the new backend APIs. `AgentBuilder` receives `agentId` + `versionId` props from the edit page, threading them through to stores and adapters.

**Tech Stack:** TypeScript, React, Zustand (builderStore), TanStack Query, Vitest

**Test framework:** Vitest with jsdom (`frontend/vitest.config.ts`). Existing test patterns in `frontend/services/__tests__/` and `frontend/components/editors/graph-builder/services/__tests__/`.

---

### Task 1: Thread `agentId` + `versionId` into AgentBuilder

The critical gap: `AgentBuilder` currently receives only `workspaceId` from the edit page. The edit page already resolves `draftVersionId` from `agent.current_draft_version_id` (line 31 of `frontend/app/agents/[agentId]/edit/page.tsx`) but doesn't pass it down.

**Files:**
- Modify: `frontend/app/agents/[agentId]/edit/page.tsx:100-102`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx` (props interface)
- Modify: `frontend/components/editors/graph-builder/stores/builderStore.ts:104-132` (state fields)

- [ ] **Step 1: Update `AgentBuilder` props interface**

In `AgentBuilder.tsx`, add `agentId` and `versionId` to the component's props interface:

```typescript
interface AgentBuilderProps {
  workspaceId: string
  agentId: string
  versionId: string
}
```

Pass these through to `builderStore.initialize()`.

- [ ] **Step 2: Update `builderStore` state to include `agentId` + `versionId`**

In `builderStore.ts`, add to state (around line 128-132):

```typescript
agentId: string | null     // new
versionId: string | null   // new
workspaceId: string | null
graphId: string | null     // keep for backward compat during migration
```

Update `initialize()` (line 261) to accept and store `agentId` + `versionId`.

- [ ] **Step 3: Update edit page to pass props**

In `frontend/app/agents/[agentId]/edit/page.tsx` line 100-102, change:

```tsx
// Before:
if (definitionKind === 'graph') return <AgentBuilder workspaceId={workspaceId} />

// After:
if (definitionKind === 'graph') {
  return (
    <AgentBuilder
      workspaceId={workspaceId}
      agentId={agentId}
      versionId={draftVersionId!}
    />
  )
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: No new type errors from these changes.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/agents/[agentId]/edit/page.tsx frontend/components/editors/graph-builder/AgentBuilder.tsx frontend/components/editors/graph-builder/stores/builderStore.ts
git commit -m "feat(graph-builder): thread agentId + versionId into AgentBuilder props"
```

---

### Task 2: Create `graphDataAdapter` + tests

Bridge `builderStore` load/save operations to `agentVersionService` (reads/writes `definition_payload`).

**Files:**
- Create: `frontend/components/editors/graph-builder/services/graphDataAdapter.ts`
- Create: `frontend/components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts`

**Reference:**
- `agentVersionService` API: `frontend/services/agentVersionService.ts` (62 lines)
  - `get(agentId, versionId, workspaceId)` → `AgentVersion` with `definition_payload`
  - `update(agentId, versionId, workspaceId, { definition_payload })` → `AgentVersion`
  - `create(agentId, workspaceId, { definition_kind, definition_payload })` → `AgentVersion`
- `GraphState` interface: `frontend/components/editors/graph-builder/utils/saveManager.ts:18-26`
  - Fields: `graphId`, `graphName`, `nodes`, `edges`, `viewport`, `graphStateFields`, `fallbackNodeId`

- [ ] **Step 1: Write failing test**

```typescript
// frontend/components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { graphDataAdapter } from '../graphDataAdapter'
import { agentVersionService } from '@/services/agentVersionService'

vi.mock('@/services/agentVersionService')

describe('graphDataAdapter', () => {
  const mockVersion = {
    id: 'v1',
    definition_payload: {
      nodes: [{ id: 'n1' }],
      edges: [{ id: 'e1' }],
      viewport: { x: 0, y: 0, zoom: 1 },
      graphStateFields: [],
      fallbackNodeId: null,
    },
  }

  beforeEach(() => vi.clearAllMocks())

  it('load returns definition_payload as GraphState', async () => {
    vi.mocked(agentVersionService.get).mockResolvedValue(mockVersion as any)
    const state = await graphDataAdapter.load('a1', 'v1', 'w1')
    expect(agentVersionService.get).toHaveBeenCalledWith('a1', 'v1', 'w1')
    expect(state.nodes).toEqual([{ id: 'n1' }])
    expect(state.edges).toEqual([{ id: 'e1' }])
  })

  it('save calls agentVersionService.update with definition_payload', async () => {
    vi.mocked(agentVersionService.update).mockResolvedValue(mockVersion as any)
    const graphState = { nodes: [{ id: 'n2' }], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }
    await graphDataAdapter.save('a1', 'v1', 'w1', graphState as any)
    expect(agentVersionService.update).toHaveBeenCalledWith('a1', 'v1', 'w1', {
      definition_payload: graphState,
    })
  })

  it('createDraft calls agentVersionService.create', async () => {
    vi.mocked(agentVersionService.create).mockResolvedValue({ id: 'v2' } as any)
    const id = await graphDataAdapter.createDraft('a1', 'w1')
    expect(id).toBe('v2')
    expect(agentVersionService.create).toHaveBeenCalledWith('a1', 'w1', {
      definition_kind: 'graph',
      definition_payload: {},
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts`
Expected: FAIL — module `../graphDataAdapter` not found.

- [ ] **Step 3: Implement `graphDataAdapter.ts`**

```typescript
// frontend/components/editors/graph-builder/services/graphDataAdapter.ts
import { agentVersionService } from '@/services/agentVersionService'
import type { GraphState } from '../utils/saveManager'

export const graphDataAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return version.definition_payload as GraphState
  },

  async save(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: Partial<GraphState>,
  ): Promise<void> {
    await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: graphState,
    })
  },

  async createDraft(
    agentId: string,
    workspaceId: string,
    basePayload?: Record<string, unknown>,
  ): Promise<string> {
    const version = await agentVersionService.create(agentId, workspaceId, {
      definition_kind: 'graph',
      definition_payload: basePayload || {},
    })
    return version.id
  },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/editors/graph-builder/services/graphDataAdapter.ts frontend/components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts
git commit -m "feat(graph-builder): add graphDataAdapter bridging builderStore to agentVersionService"
```

---

### Task 3: Wire `graphDataAdapter` into `builderStore` + `saveManager`

Replace old `agentService.saveGraphState()` / `agentService.loadGraphState()` calls.

**Files:**
- Modify: `frontend/components/editors/graph-builder/stores/builderStore.ts:261-314` (initialize/loadGraph)
- Modify: `frontend/components/editors/graph-builder/stores/builderStore.ts:688-722` (saveGraph)
- Modify: `frontend/components/editors/graph-builder/utils/saveManager.ts:43-86` (save method)

- [ ] **Step 1: Update `builderStore.initialize()` to use `graphDataAdapter.load()`**

In `builderStore.ts`, the `initialize()` method (line 261) currently calls `agentService.loadGraphState(graphId)`. Replace with:

```typescript
import { graphDataAdapter } from '../services/graphDataAdapter'

// Inside initialize():
const { agentId, versionId, workspaceId } = get()
if (!agentId || !versionId || !workspaceId) {
  throw new Error('agentId, versionId, and workspaceId are required')
}
const graphState = await graphDataAdapter.load(agentId, versionId, workspaceId)
```

Process `graphState.nodes`, `graphState.edges`, etc. the same way `loadGraph` currently does (lines 649-686).

- [ ] **Step 2: Update `saveManager.ts` save method to use `graphDataAdapter.save()`**

In `saveManager.ts`, the `save()` method (line 62) currently calls `agentService.saveGraphState(...)`. Replace:

```typescript
import { graphDataAdapter } from '../services/graphDataAdapter'

// Inside save() — replace line 62-73:
const state = this.getState()
await graphDataAdapter.save(state.agentId!, state.versionId!, state.workspaceId!, {
  nodes: state.nodes,
  edges: dedupedEdges,
  viewport: state.viewport,
  graphStateFields: state.graphStateFields,
  fallbackNodeId: state.fallbackNodeId,
})
```

The `getState` callback must now return `agentId` + `versionId` (from builderStore state).

- [ ] **Step 3: Update `GraphState` interface in `saveManager.ts`**

Add `agentId` and `versionId` to the `GraphState` interface (line 18-26):

```typescript
export interface GraphState {
  agentId: string | null    // new
  versionId: string | null  // new
  graphId: string | null    // keep for transition
  graphName: string | null
  nodes: any[]
  edges: any[]
  viewport: any
  graphStateFields: any[]
  fallbackNodeId: string | null
}
```

- [ ] **Step 4: Update existing `saveManager.test.ts`**

Read `frontend/components/editors/graph-builder/utils/__tests__/saveManager.test.ts` and update mocks to use `graphDataAdapter` instead of `agentService.saveGraphState`.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run components/editors/graph-builder/`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/editors/graph-builder/stores/builderStore.ts frontend/components/editors/graph-builder/utils/saveManager.ts frontend/components/editors/graph-builder/utils/__tests__/saveManager.test.ts
git commit -m "feat(graph-builder): wire graphDataAdapter into builderStore and saveManager"
```

---

### Task 4: Create `executionAdapter` + tests

Bridge `RunInputModal` submit → `POST /v1/runs` and execution WS subscription.

**Files:**
- Create: `frontend/components/editors/graph-builder/services/executionAdapter.ts`
- Create: `frontend/components/editors/graph-builder/services/__tests__/executionAdapter.test.ts`

**Reference:**
- `POST /v1/runs` schema (`backend/app/api/v1/agent_runs.py:52-74`): `CreateAgentRunRequest` with `release_id`, `goal`, `trigger_source`, `thread_id`, `task_id`, `input_payload`, `workspace_id`
- WS endpoint: `/ws/executions` — subscribe frame `{"type": "subscribe", "execution_id": "..."}`
- Cancel: `POST /v1/runs/{run_id}/cancel`
- Inject message: NOT YET IMPLEMENTED (Workstream 2 will add it)

- [ ] **Step 1: Write failing test**

```typescript
// frontend/components/editors/graph-builder/services/__tests__/executionAdapter.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { executionAdapter } from '../executionAdapter'

const mockFetch = vi.fn()
global.fetch = mockFetch

describe('executionAdapter', () => {
  beforeEach(() => vi.clearAllMocks())

  it('startRun posts to /api/v1/runs and returns run data', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ data: { id: 'run1', current_execution_id: 'exec1' } }),
    })

    const result = await executionAdapter.startRun({
      releaseId: 'rel1',
      prompt: 'test input',
      workspaceId: 'w1',
    })

    expect(mockFetch).toHaveBeenCalledWith('/api/v1/runs', expect.objectContaining({
      method: 'POST',
    }))
    expect(result.id).toBe('run1')
    expect(result.current_execution_id).toBe('exec1')
  })

  it('cancelRun posts to /api/v1/runs/{id}/cancel', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ data: {} }) })
    await executionAdapter.cancelRun('run1')
    expect(mockFetch).toHaveBeenCalledWith('/api/v1/runs/run1/cancel', expect.objectContaining({
      method: 'POST',
    }))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run components/editors/graph-builder/services/__tests__/executionAdapter.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `executionAdapter.ts`**

```typescript
// frontend/components/editors/graph-builder/services/executionAdapter.ts
const API_BASE = '/api/v1'

interface StartRunParams {
  releaseId: string
  prompt: string
  workspaceId: string
  threadId?: string
  taskId?: string
}

interface RunResult {
  id: string
  current_execution_id: string
  status: string
}

async function apiPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const json = await res.json()
  return json.data
}

export const executionAdapter = {
  async startRun(params: StartRunParams): Promise<RunResult> {
    return apiPost<RunResult>('/runs', {
      release_id: params.releaseId,
      goal: params.prompt,
      workspace_id: params.workspaceId,
      trigger_source: 'api',
      thread_id: params.threadId,
      task_id: params.taskId,
    })
  },

  subscribeToExecution(executionId: string): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/executions`)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe', execution_id: executionId }))
    }
    return ws
  },

  async cancelRun(runId: string): Promise<void> {
    await apiPost(`/runs/${runId}/cancel`, {})
  },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run components/editors/graph-builder/services/__tests__/executionAdapter.test.ts`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/editors/graph-builder/services/executionAdapter.ts frontend/components/editors/graph-builder/services/__tests__/executionAdapter.test.ts
git commit -m "feat(graph-builder): add executionAdapter for POST /v1/runs + WS subscription"
```

---

### Task 5: Wire `executionAdapter` into `executionStore`

Replace `workspaceChatWsService.sendChat()` with `executionAdapter.startRun()` + WS subscription.

**Files:**
- Modify: `frontend/components/editors/graph-builder/stores/execution/executionStore.ts:384-514` (startExecution)
- Modify: `frontend/components/editors/graph-builder/stores/execution/executionStore.ts:516-539` (stopExecution)

- [ ] **Step 1: Rewrite `startExecution` to use `executionAdapter`**

In `executionStore.ts`, the `startExecution(input)` method (line 384) currently:
1. Resolves `graphId` from `agentService.getCachedGraphId()` (localStorage)
2. Calls `workspaceChatWsService.sendChat({ message: input, graphId, ... })`

Replace with:
1. Read `agentId`, `versionId`, `workspaceId` from `builderStore` state
2. Resolve `releaseId` — either from `builderStore.activeReleaseId` or by deploying first
3. Call `executionAdapter.startRun({ releaseId, prompt: input, workspaceId })`
4. Call `executionAdapter.subscribeToExecution(run.current_execution_id)`
5. Process WS events through existing `processEvent` pipeline

```typescript
import { executionAdapter } from '../../services/executionAdapter'
import { useBuilderStore } from '../builderStore'

// Inside startExecution(input):
const { agentId, versionId, workspaceId } = useBuilderStore.getState()
if (!agentId || !workspaceId) throw new Error('Missing agent context')

// Get active release from agent (or from builderStore if cached)
const agent = await agentService.getAgent(agentId, workspaceId)
if (!agent.active_release_id) throw new Error('Agent has no active release. Deploy first.')

const run = await executionAdapter.startRun({
  releaseId: agent.active_release_id,
  prompt: input,
  workspaceId,
})

// Subscribe to execution events via WS
const ws = executionAdapter.subscribeToExecution(run.current_execution_id)
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  // Route to existing event processing pipeline
  processEvent(data, ctx, storeAdapter)
}
```

- [ ] **Step 2: Rewrite `stopExecution` to use `executionAdapter.cancelRun()`**

Replace `workspaceChatWsService.stopByThreadId(context.threadId)` (line 523) with:

```typescript
if (context.runId) {
  await executionAdapter.cancelRun(context.runId)
}
```

Add `runId` to `ExecutionContext` type if not already present.

- [ ] **Step 3: Run type check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/editors/graph-builder/stores/execution/executionStore.ts
git commit -m "feat(graph-builder): wire executionAdapter into executionStore start/stop"
```

---

### Task 6: Wire `deploymentAdapter` into `BuilderToolbar.handleDeploy`

**Files:**
- Modify: `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx:97-128`

- [ ] **Step 1: Import and wire `deploymentAdapter`**

In `BuilderToolbar.tsx`, replace the stub `handleDeploy` (lines 97-128):

```typescript
import { deploymentAdapter } from '../services/deploymentAdapter'
import { useBuilderStore } from '../stores/builderStore'

const handleDeploy = async () => {
  if (isDeploying || !agentId || nodesCount === 0) return

  const { versionId } = useBuilderStore.getState()
  if (!versionId) {
    toast({ title: 'No version to deploy', variant: 'destructive' })
    return
  }

  setIsDeploying(true)
  try {
    await deploymentAdapter.deploy(agentId, versionId, workspaceId)

    queryClient.invalidateQueries({ queryKey: graphKeys.deployment(agentId) })
    queryClient.invalidateQueries({ queryKey: graphKeys.versions(agentId) })
    queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })

    toast({
      title: t('workspace.deploySuccess'),
      description: t('workspace.deploySuccessDescription', { version: 'latest' }),
      variant: 'success',
    })
  } catch (error) {
    console.error('Deploy failed:', error)
    toast({
      title: t('workspace.deployFailed'),
      description: error instanceof Error ? error.message : t('workspace.deployFailedDescription'),
      variant: 'destructive',
    })
  } finally {
    setIsDeploying(false)
  }
}
```

- [ ] **Step 2: Run type check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: No type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/editors/graph-builder/components/BuilderToolbar.tsx
git commit -m "feat(graph-builder): wire deploymentAdapter into BuilderToolbar deploy action"
```

---

### Task 7: Rewrite `useDeploymentHistory`

Full rewrite (~402 lines → cleaner hook using `deploymentAdapter` + React Query).

**Files:**
- Modify: `frontend/components/editors/graph-builder/hooks/useDeploymentHistory.ts` (full rewrite)
- Modify: `frontend/components/editors/graph-builder/components/DeploymentVersionsList.tsx` (update prop types if needed)

**Reference:**
- `deploymentAdapter` API: `frontend/components/editors/graph-builder/services/deploymentAdapter.ts`
  - `deploy(agentId, versionId, workspaceId)` → `DeploymentVersion`
  - `list(agentId, workspaceId)` → `DeploymentVersion[]`
  - `activate(agentId, releaseId, workspaceId)` → void
  - `retire(agentId, releaseId, workspaceId)` → void
- Current hook returns (lines 352-400): `deploymentStatus`, `versions`, `totalVersions`, `handlers`, confirmation dialogs, pagination, preview mode

- [ ] **Step 1: Rewrite the hook**

Key changes:
1. Replace all stubbed `graphDeploymentService` / `deploymentStore` calls with `deploymentAdapter` methods
2. Replace `useDeploymentVersions(graphId, ...)` query with `useQuery` wrapping `deploymentAdapter.list()`
3. Remove `fetchVersionState` (used old `graphDeploymentService.getVersionState` — preview of version state can use `agentVersionService.get()` to read `definition_payload`)
4. Wire `handleConfirmRevert` → `deploymentAdapter.activate(agentId, releaseId, workspaceId)`
5. Wire `handleConfirmDelete` → `deploymentAdapter.retire(agentId, releaseId, workspaceId)`
6. Wire `handleConfirmUndeploy` → `deploymentAdapter.retire(agentId, releaseId, workspaceId)`
7. Remove `handleSaveName` (rename is not in the new API — drop this feature or add it later)

The return interface shape should stay the same so `DeploymentHistoryPanel` doesn't need major changes.

- [ ] **Step 2: Update `DeploymentVersionsList` prop types**

The `DeploymentVersionsList` component receives `versions` as `GraphDeploymentVersion[]`. Update the type to match `DeploymentVersion` from `deploymentAdapter.ts`:

```typescript
interface DeploymentVersion {
  id: string
  version: number
  status: string
  runtime_kind: string
  published_at: string | null
}
```

Update any `(deploymentStatus as any)` casts on lines 101, 108 with proper typed access.

- [ ] **Step 3: Run type check + tests**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Run: `cd frontend && npx vitest run components/editors/graph-builder/`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/editors/graph-builder/hooks/useDeploymentHistory.ts frontend/components/editors/graph-builder/components/DeploymentVersionsList.tsx
git commit -m "refactor(graph-builder): rewrite useDeploymentHistory to use deploymentAdapter"
```

---

### Task 8: Cleanup old references

Remove dead code paths that referenced the old `graphs/{id}/state` API.

**Files:**
- Modify: `frontend/hooks/queries/graphs.ts` — remove old endpoint calls
- Modify: `frontend/components/editors/graph-builder/stores/builderStore.ts` — remove legacy `saveGraph` path that calls `agentService.saveGraph`
- Review: `frontend/components/editors/graph-builder/services/agentService.ts` — check if `saveGraphState()`, `loadGraphState()`, `getCachedGraphId()` have any remaining callers; if not, remove

- [ ] **Step 1: Audit remaining references to old graph API**

Run: `cd frontend && grep -r "saveGraphState\|loadGraphState\|getCachedGraphId\|graphs/.*state" --include="*.ts" --include="*.tsx" -l`

For each file found, verify whether it's still called or can be removed.

- [ ] **Step 2: Remove dead code**

Remove unused functions/imports identified in step 1. Keep any that are still referenced by the old `/workspace` route (which Workstream 3 will delete).

- [ ] **Step 3: Run full build**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add -u frontend/
git commit -m "chore(graph-builder): remove dead references to old graphs API"
```
