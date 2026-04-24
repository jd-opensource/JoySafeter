# Event Architecture Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all old/new architecture inconsistencies — fix broken WS protocol, rewrite the dead event pipeline with native handlers, remove all dead code, and align routes/types.

**Architecture:** Three layers executed sequentially. L1 fixes protocol bugs and deletes backend dead code. L2 rewrites the frontend event pipeline in executionStore and deletes the old pipeline files. L3 fixes routes, types, and component duplication. Each layer ends with a verification step.

**Tech Stack:** Python/FastAPI (backend), Next.js/TypeScript/Zustand (frontend), WebSocket event streaming.

**Spec:** `docs/superpowers/specs/2026-04-24-event-architecture-cleanup-design.md`

---

## Task 1: Backend Minor Fixes

**Files:**
- Modify: `backend/app/core/events/subscribers/persistence.py:65`
- Modify: `backend/app/services/execution_service.py:220`
- Modify: `backend/app/websocket/execution_subscription_manager.py:12-13`
- Modify: `backend/app/schemas/execution.py:67-68`

- [ ] **Step 1: Fix persistence.py string literal**

In `backend/app/core/events/subscribers/persistence.py`, change line 65 from:
```python
        if envelope.event_type == "execution_completed":
```
to:
```python
        if envelope.event_type == ExecutionEventType.EXECUTION_COMPLETED:
```

Add import at the top (after the existing envelope import):
```python
from app.core.events.event_types import ExecutionEventType
```

- [ ] **Step 2: Fix execution_service.py unreachable code**

In `backend/app/services/execution_service.py`, delete line 220:
```python
        return results
```
This line is after the `return [...]` on lines 210-218 and can never execute.

- [ ] **Step 3: Fix execution_subscription_manager.py stale docstring**

In `backend/app/websocket/execution_subscription_manager.py`, replace the class docstring:
```python
    """Tracks which WebSocket connections are subscribed to which execution IDs.

    Mirrors RunSubscriptionManager but scoped to CLI agent executions.
    """
```
with:
```python
    """Tracks which WebSocket connections are subscribed to which execution IDs."""
```

- [ ] **Step 4: Delete duplicate InjectMessageRequest from schemas/execution.py**

In `backend/app/schemas/execution.py`, delete lines 67-68:
```python
class InjectMessageRequest(BaseModel):
    message: str
```
The canonical definition is in `backend/app/schemas/task.py:85` and is the one imported by `backend/app/api/v1/executions.py:26`.

- [ ] **Step 5: Verify backend compiles**

Run: `cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter && python -m py_compile backend/app/core/events/subscribers/persistence.py && python -m py_compile backend/app/services/execution_service.py && python -m py_compile backend/app/websocket/execution_subscription_manager.py && python -m py_compile backend/app/schemas/execution.py && echo "OK"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/events/subscribers/persistence.py backend/app/services/execution_service.py backend/app/websocket/execution_subscription_manager.py backend/app/schemas/execution.py
git commit -m "fix: backend minor fixes — use event constant, remove dead code, fix docstring"
```

---

## Task 2: Delete Backend Dead Code

**Files:**
- Delete: `backend/app/schemas/runs.py`
- Modify: `backend/app/api/v1/copilot.py` (remove `/stream` endpoint)
- Modify: `backend/app/schemas/copilot.py` (remove `CopilotStreamRequest`)

- [ ] **Step 1: Delete schemas/runs.py**

```bash
rm backend/app/schemas/runs.py
```

Verify no imports remain:
```bash
grep -r "from app.schemas.runs" backend/app/ && echo "DANGLING IMPORT FOUND" || echo "Clean"
grep -r "from app.schemas import.*runs" backend/app/ && echo "DANGLING IMPORT FOUND" || echo "Clean"
```
Expected: `Clean` for both.

- [ ] **Step 2: Remove legacy /stream endpoint from copilot.py**

In `backend/app/api/v1/copilot.py`, delete the entire `/stream` endpoint (lines 18-41):
```python
@router.post("/stream")
async def copilot_stream(
    body: CopilotStreamRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream copilot graph-editing actions as Server-Sent Events (legacy)."""
    service = CopilotService(
        user_id=str(current_user.id),
        provider_name=body.provider_name,
        model_name=body.model_name,
        db=db,
    )

    async def event_generator():
        async for event in service.generate_actions_stream(
            prompt=body.prompt,
            graph_context=body.graph_context,
            conversation_history=body.conversation_history,
            mode=body.mode or "deepagents",
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Also remove the now-unused imports:
- `import json` (only used by the deleted endpoint)
- `StreamingResponse` from `fastapi.responses`
- `CopilotStreamRequest` from the schemas import

Update the file's docstring:
```python
"""Copilot API — execution-engine dispatch."""
```

Update the import line to:
```python
from app.schemas.copilot import CopilotRunRequest, CopilotRunResponse
```

- [ ] **Step 3: Delete CopilotStreamRequest from copilot schema**

In `backend/app/schemas/copilot.py`, delete lines 7-13:
```python
class CopilotStreamRequest(BaseModel):
    provider_name: str
    model_name: str
    prompt: str
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]]
    mode: Optional[str] = None
```

Also remove unused `Any` import if `CopilotRunRequest` still uses it (it does — keep `Any`). Remove `Optional` only if unused (check: `CopilotRunRequest` still uses `Optional` — keep it).

- [ ] **Step 4: Verify backend compiles**

Run: `python -m py_compile backend/app/api/v1/copilot.py && python -m py_compile backend/app/schemas/copilot.py && echo "OK"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add -u backend/app/schemas/runs.py backend/app/api/v1/copilot.py backend/app/schemas/copilot.py
git commit -m "refactor: remove dead backend code — schemas/runs.py, legacy copilot/stream endpoint"
```

---

## Task 3: WS Frame Protocol Alignment

**Files:**
- Modify: `frontend/lib/ws/executions/types.ts`
- Modify: `frontend/lib/ws/executions/executionWsClient.ts`

- [ ] **Step 1: Update types.ts — callbacks and frame union**

In `frontend/lib/ws/executions/types.ts`:

Delete the `ExecutionStatusFrame` interface (lines 25-29):
```typescript
export interface ExecutionStatusFrame {
  type: 'execution_status'
  execution_id: string
  status: string
}
```

Update `IncomingExecutionWsFrame` union — remove `ExecutionStatusFrame`:
```typescript
export type IncomingExecutionWsFrame =
  | ExecutionSnapshotFrame
  | ExecutionEventFrame
  | ExecutionCompletedFrame
  | ExecutionReplayDoneFrame
  | ExecutionWsErrorFrame
```

Update `ExecutionSubscriptionCallbacks` — remove `onStatus`, add `onCompleted` and `onReplayDone`:
```typescript
export interface ExecutionSubscriptionCallbacks {
  onSnapshot?: (frame: ExecutionSnapshotFrame) => void
  onEvent?: (frame: ExecutionEventFrame) => void
  onCompleted?: (frame: ExecutionCompletedFrame) => void
  onReplayDone?: (frame: ExecutionReplayDoneFrame) => void
  onError?: (message: string) => void
}
```

- [ ] **Step 2: Update executionWsClient.ts — handleMessage**

In `frontend/lib/ws/executions/executionWsClient.ts`, replace the `handleMessage` method (lines 35-58):

```typescript
  protected handleMessage(frame: IncomingExecutionWsFrame): void {
    if (frame.type === 'ws_error') {
      this.subscriptions.forEach(({ callbacks }) => callbacks.onError?.(frame.message))
      return
    }

    const execId = 'execution_id' in frame ? frame.execution_id : undefined
    if (!execId) return
    const subscription = this.subscriptions.get(execId)
    if (!subscription) return
    const { callbacks } = subscription

    if (frame.type === 'snapshot') {
      subscription.afterSeq = Math.max(subscription.afterSeq, frame.last_seq)
      callbacks.onSnapshot?.(frame)
    }
    if (frame.type === 'event') {
      if (frame.seq <= subscription.afterSeq) return
      subscription.afterSeq = frame.seq
      callbacks.onEvent?.(frame)
    }
    if (frame.type === 'execution_completed') {
      callbacks.onCompleted?.(frame)
    }
    if (frame.type === 'replay_done') {
      subscription.afterSeq = Math.max(subscription.afterSeq, frame.last_seq)
      callbacks.onReplayDone?.(frame)
    }
  }
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

Check: no errors related to `executionWsClient`, `types.ts`, or `ExecutionStatusFrame`. (Other pre-existing errors are acceptable.)

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/ws/executions/types.ts frontend/lib/ws/executions/executionWsClient.ts
git commit -m "fix: align WS frame protocol — handle execution_completed/replay_done, remove phantom execution_status"
```

---

## Task 4: Rewrite executionStore — Native Event Handlers + Auth WS

This is the core task. It combines the WS auth fix (L1.1), snapshot parsing fix (L1.3), and native event pipeline (L2.1-2.4) because they all touch `executionStore.ts` and are interdependent.

**Files:**
- Modify: `frontend/components/editors/graph-builder/stores/execution/types.ts`
- Modify: `frontend/components/editors/graph-builder/stores/execution/ExecutionManager.ts`
- Modify: `frontend/components/editors/graph-builder/stores/execution/executionStore.ts`
- Modify: `frontend/components/editors/graph-builder/services/executionAdapter.ts`

- [ ] **Step 1: Update ExecutionContext in types.ts**

In `frontend/components/editors/graph-builder/stores/execution/types.ts`:

Remove the import of `GraphState` and `TraceStep` from `eventProcessor` (line 9):
```typescript
import type { GraphState, TraceStep } from '../../services/eventProcessor'
```

Define them locally instead (minimal versions needed by the store):
```typescript
export interface GraphState {
  context?: Record<string, unknown>
  messages?: unknown[]
  current_node?: string
}

export interface TraceStep {
  nodeId: string
  nodeType: string
  timestamp: number
  command: { update: Record<string, unknown>; goto?: string; reason?: string }
  stateSnapshot: GraphState
  routeDecision?: { result: boolean | string; reason: string; goto: string }
}
```

Update `ExecutionContext` — remove `threadId`, `requestId`, `executionWs`; add `subscribedExecutionId`:
```typescript
export interface ExecutionContext {
  graphId: string
  abortController: AbortController | null
  /** Run ID returned by executionAdapter.startRun — used for cancel */
  runId: string | null
  /** Execution ID currently subscribed to via SharedExecutionWsClient */
  subscribedExecutionId: string | null
  /** Timeout handle — cleared on normal completion, fires to force-stop stalled executions */
  timeoutId: ReturnType<typeof setTimeout> | null
  state: GraphExecutionState
}
```

Update `ExecutionStoreActions` — remove `setThreadId`, `setRequestId`, `setExecutionWs`; add `setSubscribedExecutionId`:
```typescript
  // Execution context management
  getContext: (graphId: string) => ExecutionContext
  setAbortController: (graphId: string, controller: AbortController | null) => void
  setRunId: (graphId: string, runId: string | null) => void
  setSubscribedExecutionId: (graphId: string, executionId: string | null) => void
  setTimeoutId: (graphId: string, timeoutId: ReturnType<typeof setTimeout> | null) => void
```

- [ ] **Step 2: Update ExecutionManager.ts**

In `frontend/components/editors/graph-builder/stores/execution/ExecutionManager.ts`:

Update `createExecutionContext` to match new `ExecutionContext` shape:
```typescript
export function createExecutionContext(graphId: string): ExecutionContext {
  return {
    graphId,
    abortController: null,
    runId: null,
    subscribedExecutionId: null,
    timeoutId: null,
    state: createEmptyGraphState(),
  }
}
```

- [ ] **Step 3: Remove subscribeToExecution from executionAdapter.ts**

In `frontend/components/editors/graph-builder/services/executionAdapter.ts`:

Delete the `subscribeToExecution` method (lines 30-37):
```typescript
  subscribeToExecution(executionId: string): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/executions`)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe', execution_id: executionId }))
    }
    return ws
  },
```

- [ ] **Step 4: Rewrite executionStore.ts**

This is the largest change. The full rewritten file replaces ALL old pipeline code with native handlers.

In `frontend/components/editors/graph-builder/stores/execution/executionStore.ts`:

**Remove these imports:**
```typescript
import type { ChatStreamEvent } from '@/services/chatBackend'
import type { GraphState, TraceStep } from '../../services/eventProcessor'
import {
  processEvent,
  createEventProcessorContext,
  type EventProcessorStore,
} from '../../services/eventProcessor'
import { agentService } from '../../services/agentService'
```

**Add these imports:**
```typescript
import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import type { ExecutionEventFrame, ExecutionCompletedFrame, ExecutionSnapshotFrame } from '@/lib/ws/executions/types'
import type { GraphState, TraceStep } from './types'
```

**Replace the `startExecution` method** (lines 416-651) with the new implementation that:
1. Uses `getExecutionWsClient().subscribe()` instead of raw WebSocket
2. Maps `ExecutionEventFrame` directly to `ExecutionStep` via a local `handleExecutionEvent` function
3. Handles `onSnapshot` by reading `frame.status` (not `frame.payload`)
4. Handles `onCompleted` to finalize execution
5. Removes the `agentService.getCachedGraphId()` fallback

The new `handleExecutionEvent` function inside `startExecution`:

```typescript
    // Local tracking for tool step correlation
    const toolStepMap = new Map<string, string>()
    let currentThoughtId: string | null = null

    function handleExecutionEvent(frame: ExecutionEventFrame) {
      const payload = frame.payload as Record<string, unknown>
      const eventType = frame.event_type

      switch (eventType) {
        case 'assistant_text': {
          const delta = (payload.delta as string) ?? (payload.text as string) ?? ''
          if (!delta) return
          if (!currentThoughtId) {
            const stepId = generateId('thought')
            currentThoughtId = stepId
            store.addStep({
              id: stepId,
              nodeId: 'agent',
              nodeLabel: 'Agent',
              stepType: 'agent_thought',
              title: 'Reasoning',
              status: 'running',
              startTime: Date.now(),
              content: delta,
            })
          } else {
            store.appendContent(currentThoughtId, delta)
          }
          break
        }
        case 'thinking': {
          if (currentThoughtId) {
            store.updateStep(currentThoughtId, { status: 'success', endTime: Date.now() })
          }
          const stepId = generateId('thinking')
          currentThoughtId = stepId
          store.addStep({
            id: stepId,
            nodeId: 'agent',
            nodeLabel: 'Agent',
            stepType: 'agent_thought',
            title: 'Thinking',
            status: 'running',
            startTime: Date.now(),
            content: (payload.content as string) ?? '',
          })
          break
        }
        case 'tool_use_start': {
          if (currentThoughtId) {
            store.updateStep(currentThoughtId, { status: 'success', endTime: Date.now() })
            currentThoughtId = null
          }
          const toolId = generateId('tool')
          const toolUseId = (payload.tool_use_id as string) ?? toolId
          const toolName = (payload.name as string) ?? (payload.tool_name as string) ?? 'tool'
          toolStepMap.set(toolUseId, toolId)
          store.addStep({
            id: toolId,
            nodeId: 'tool',
            nodeLabel: toolName,
            stepType: 'tool_execution',
            title: toolName,
            status: 'running',
            startTime: Date.now(),
            data: { request: payload.input },
          })
          break
        }
        case 'tool_use_end': {
          const toolUseId = (payload.tool_use_id as string) ?? ''
          const toolStepId = toolStepMap.get(toolUseId)
          if (toolStepId) {
            toolStepMap.delete(toolUseId)
            store.updateStep(toolStepId, {
              status: (payload.is_error ? 'error' : 'success') as 'success' | 'error',
              endTime: Date.now(),
              data: { response: payload.output ?? payload.result },
            })
          }
          break
        }
        case 'error': {
          const msg = (payload.message as string) ?? 'Unknown error'
          const code = (payload.code as string) ?? ''
          if (code === 'stopped' || msg === 'Stream stopped' || msg.includes('stopped')) {
            wasStopped = true
            return
          }
          store.addStep({
            id: generateId('error'),
            nodeId: 'system',
            nodeLabel: 'Error',
            stepType: 'system_log',
            title: 'Error',
            status: 'error',
            startTime: Date.now(),
            content: msg,
          })
          break
        }
        case 'artifact_created': {
          store.addStep({
            id: generateId('artifact'),
            nodeId: 'agent',
            nodeLabel: 'Artifact',
            stepType: 'artifact',
            title: (payload.name as string) ?? 'Artifact',
            status: 'success',
            startTime: Date.now(),
            data: payload,
          })
          break
        }
        case 'approval_requested': {
          store.addInterrupt({
            nodeId: (payload.node_id as string) ?? 'agent',
            nodeLabel: (payload.node_label as string) ?? 'Agent',
            state: (payload.state as Record<string, unknown>) ?? {},
            threadId: '',
          })
          break
        }
        case 'approval_resolved': {
          const nodeId = (payload.node_id as string) ?? 'agent'
          store.removeInterrupt(nodeId)
          break
        }
        case 'execution_started':
        case 'execution_status_change':
        case 'execution_completed':
        case 'user_message':
          // Lifecycle events handled at the frame level (onCompleted callback) or ignored
          break
        default:
          // copilot_* events and unknown types: ignore in executionStore
          break
      }
    }
```

**Replace the WS connection block** in `startExecution` (the `try` block starting around line 512). The new version:

```typescript
      try {
        const agent = await globalAgentService.get(agentId, workspaceId)
        const releaseId = agent.active_release_id
        if (!releaseId) {
          throw new Error('Agent has no active release. Please publish the agent first.')
        }

        const run = await executionAdapter.startRun({
          releaseId,
          prompt: input,
          workspaceId,
        })
        store.setRunId(graphId, run.id)

        const executionId = run.current_execution_id
        store.setSubscribedExecutionId(graphId, executionId)

        // Set execution timeout
        const timeoutId = setTimeout(() => {
          const context = getOrCreateContext(get().contexts, graphId)
          if (context.runId) {
            executionAdapter.cancelRun(context.runId).catch(() => {})
          }
          if (context.subscribedExecutionId) {
            getExecutionWsClient().unsubscribe(context.subscribedExecutionId)
          }
          store.addStep({
            id: generateId('timeout'),
            nodeId: 'system',
            nodeLabel: 'System',
            stepType: 'system_log',
            title: 'Execution Timeout',
            status: 'error',
            startTime: Date.now(),
            content: 'Execution timed out after 10 minutes',
          })
          store.updateGraphState(graphId, { isExecuting: false })
        }, EXECUTION_TIMEOUT_MS)
        store.setTimeoutId(graphId, timeoutId)

        // Subscribe via authenticated shared WS client
        await new Promise<void>((resolve) => {
          const onAbort = () => {
            wasStopped = true
            getExecutionWsClient().unsubscribe(executionId)
            resolve()
          }
          abortController.signal.addEventListener('abort', onAbort, { once: true })

          getExecutionWsClient().subscribe(executionId, 0, {
            onSnapshot: (frame: ExecutionSnapshotFrame) => {
              // Replay any events included in the snapshot
              // (currently backend sends empty events array, but handle it correctly)
              for (const evt of frame.events) {
                handleExecutionEvent({
                  type: 'event',
                  execution_id: frame.execution_id,
                  seq: evt.seq,
                  event_type: evt.event_type,
                  payload: evt.payload,
                  created_at: evt.created_at,
                })
              }
            },
            onEvent: (frame: ExecutionEventFrame) => {
              handleExecutionEvent(frame)
            },
            onCompleted: (frame: ExecutionCompletedFrame) => {
              if (currentThoughtId) {
                store.updateStep(currentThoughtId, { status: 'success', endTime: Date.now() })
                currentThoughtId = null
              }
              const terminalStatus = frame.status
              if (!wasStopped) {
                const workflowStep = store.getContext(graphId).state.steps.find((s) => s.id === workflowId)
                store.updateStep(workflowId, {
                  status: terminalStatus === 'succeeded' ? 'success' : 'error',
                  endTime: Date.now(),
                  duration: Date.now() - (workflowStep?.startTime || Date.now()),
                })
              }
              abortController.signal.removeEventListener('abort', onAbort)
              resolve()
            },
            onReplayDone: () => {
              // Catch-up replay complete — now receiving live events
            },
            onError: (message: string) => {
              console.warn('[executionStore] WS error:', message)
            },
          })
        })
      } catch { ... } finally { ... }
```

**Update the `finally` block** to use the new field names:
```typescript
      } finally {
        const finalContext = store.getContext(graphId)
        if (finalContext.timeoutId !== null) {
          clearTimeout(finalContext.timeoutId)
        }
        if (finalContext.subscribedExecutionId) {
          getExecutionWsClient().unsubscribe(finalContext.subscribedExecutionId)
        }
        store.updateGraphState(graphId, { isExecuting: false })
        store.setAbortController(graphId, null)
        store.setRunId(graphId, null)
        store.setSubscribedExecutionId(graphId, null)
        store.setTimeoutId(graphId, null)
      }
```

**Replace `stopExecution`** to use `getExecutionWsClient().unsubscribe()`:
```typescript
    stopExecution: async () => {
      const {
        currentGraphId,
        getContext,
        setAbortController,
        setRunId,
        setSubscribedExecutionId,
        updateGraphState,
      } = get()
      if (!currentGraphId) return

      const context = getContext(currentGraphId)

      if (context.runId) {
        try {
          await executionAdapter.cancelRun(context.runId)
        } catch (error) {
          console.error('Failed to cancel run on backend:', error)
          get().addStep({
            id: generateId('cancel-error'),
            nodeId: 'system',
            nodeLabel: 'System',
            stepType: 'system_log',
            title: 'Cancel Failed',
            status: 'error',
            startTime: Date.now(),
            content: 'Failed to cancel execution on server. It may still be running.',
          })
        }
        setRunId(currentGraphId, null)
      }

      if (context.subscribedExecutionId) {
        getExecutionWsClient().unsubscribe(context.subscribedExecutionId)
        setSubscribedExecutionId(currentGraphId, null)
      }

      if (context.abortController) {
        context.abortController.abort()
        setAbortController(currentGraphId, null)
      }

      updateGraphState(currentGraphId, { isExecuting: false, activeNodeId: null })
    },
```

**Remove dead store methods:** Delete `setThreadId`, `setRequestId`, `setExecutionWs`. Replace them with `setSubscribedExecutionId`.

**Update `clearGraphState`** to unsubscribe instead of closing raw WS:
```typescript
    clearGraphState: (graphId: string) => {
      const { contexts, currentGraphId } = get()
      const context = contexts.get(graphId)
      if (context?.subscribedExecutionId) {
        try { getExecutionWsClient().unsubscribe(context.subscribedExecutionId) } catch { /* ignore */ }
      }
      if (context?.abortController) {
        context.abortController.abort()
      }
      if (context?.timeoutId !== null && context?.timeoutId !== undefined) {
        clearTimeout(context.timeoutId)
      }
      // ... rest unchanged
    },
```

**Remove `agentService.getCachedGraphId()` fallback** — change line 428:
```typescript
      const graphId = store.currentGraphId
```

Remove the import of `agentService` from `../../services/agentService` (the local one, not `globalAgentService`).

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend && npx tsc --noEmit --pretty 2>&1 | head -50`

Fix any type errors. The most likely issues:
- `ExecutionStep` may not have an `artifact` step type — check the type definition and add if needed.
- `handleExecutionEvent` references within the Promise need correct closure scope.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/editors/graph-builder/stores/execution/types.ts frontend/components/editors/graph-builder/stores/execution/ExecutionManager.ts frontend/components/editors/graph-builder/stores/execution/executionStore.ts frontend/components/editors/graph-builder/services/executionAdapter.ts
git commit -m "refactor: rewrite executionStore — authenticated WS, native event handlers, remove old pipeline"
```

---

## Task 5: Delete Frontend Dead Code

This task can only run AFTER Task 4 (which removes all imports of the old pipeline).

**Files:**
- Delete: `frontend/services/chatBackend.ts`
- Delete: `frontend/lib/ws/chat/chatWsClient.ts`
- Delete: `frontend/lib/ws/chat/types.ts`
- Delete: `frontend/lib/ws/chat/errors.ts`
- Delete: `frontend/components/editors/graph-builder/services/eventAdapter.ts`
- Delete: `frontend/components/editors/graph-builder/services/eventProcessor.ts`
- Modify: `frontend/components/editors/graph-builder/services/index.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`

- [ ] **Step 1: Delete old pipeline files**

```bash
rm frontend/services/chatBackend.ts
rm frontend/lib/ws/chat/chatWsClient.ts
rm frontend/lib/ws/chat/types.ts
rm frontend/lib/ws/chat/errors.ts
rm frontend/components/editors/graph-builder/services/eventAdapter.ts
rm frontend/components/editors/graph-builder/services/eventProcessor.ts
```

- [ ] **Step 2: Clean up services/index.ts**

In `frontend/components/editors/graph-builder/services/index.ts`, remove the eventAdapter exports. Result:
```typescript
export { agentService } from './agentService'
export { nodeRegistry } from './nodeRegistry'
```

- [ ] **Step 3: Clean up useCopilotWebSocketHandler.ts**

In `frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts`:

Remove the `ChatStreamEvent` import (line 19):
```typescript
import type { ChatStreamEvent } from '@/services/chatBackend'
```

Delete the `handleCopilotEvent` function (lines 169-218) and update the return (line 220):
```typescript
  return callbacks
```
(Was `return { ...callbacks, handleCopilotEvent }`)

- [ ] **Step 4: Update CopilotPanel.tsx to match new return type**

In `frontend/components/editors/graph-builder/components/CopilotPanel.tsx`, the line:
```typescript
const webSocketCallbacks = useCopilotWebSocketHandler({ state, actions, refs, graphId })
```
Now returns the callbacks object directly (no spread). The usage at lines 55-63 (`webSocketCallbacks.onStatus`, etc.) continues to work because the callbacks are properties of the returned object.

No code change needed here — verify it still compiles.

- [ ] **Step 5: Verify no dangling imports**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend
grep -r "chatBackend" --include="*.ts" --include="*.tsx" . && echo "DANGLING" || echo "Clean"
grep -r "eventAdapter" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next" && echo "CHECK ABOVE" || echo "Clean"
grep -r "eventProcessor" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next" && echo "CHECK ABOVE" || echo "Clean"
grep -r "getChatWsClient\|ChatWsClient\|ChatWsFrame\|ChatStreamEvent" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next" && echo "CHECK ABOVE" || echo "Clean"
```

Expected: All `Clean`.

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

- [ ] **Step 7: Commit**

```bash
git add -u frontend/services/chatBackend.ts frontend/lib/ws/chat/ frontend/components/editors/graph-builder/services/eventAdapter.ts frontend/components/editors/graph-builder/services/eventProcessor.ts frontend/components/editors/graph-builder/services/index.ts frontend/components/editors/graph-builder/hooks/useCopilotWebSocketHandler.ts
git commit -m "refactor: delete dead frontend code — chatBackend, chat WS, eventAdapter, eventProcessor"
```

---

## Task 6: Verify Layer 1+2 Flows

- [ ] **Step 1: Verify Flow A (Graph Builder Execution)**

Trace the code path manually:
1. `executionStore.startExecution()` → calls `executionAdapter.startRun()` → `POST /v1/runs` ✓
2. `getExecutionWsClient().subscribe(executionId, 0, callbacks)` → authenticated WS ✓
3. `onEvent` callback → `handleExecutionEvent()` maps to `ExecutionStep` ✓
4. `onCompleted` callback → finalizes workflow step ✓
5. `stopExecution()` → `executionAdapter.cancelRun()` + `unsubscribe()` ✓

- [ ] **Step 2: Verify Flow B (Copilot Panel)**

Trace:
1. `useCopilotActions.handleSend()` → `copilotService.dispatchRun()` → `POST /v1/copilot/run` ✓
2. `useCopilotExecutionBridge` → `useExecutionStream` → `getExecutionWsClient().subscribe()` ✓
3. `copilot_*` events dispatched to `useCopilotWebSocketHandler` callbacks ✓
4. `handleCopilotEvent` removed but callbacks still exported and used ✓

- [ ] **Step 3: Commit verification marker**

No code change. Proceed to Layer 3.

---

## Task 7: Route Fixes

**Files:**
- Modify: `frontend/app/executions/[executionId]/page.tsx:57`
- Modify: `frontend/components/tasks/task-detail-panel.tsx:616,633,649`
- Modify: `frontend/components/tasks/task-card.tsx:95,140`
- Modify: `frontend/components/tasks/task-list-view.tsx:144,155`
- Modify: `frontend/components/executions/executions-tab.tsx:72`
- Modify: `frontend/components/agents/agent-overview-tab.tsx:119`

- [ ] **Step 1: Fix /runs links in all files**

Replace all `"/runs"` and `"/runs?..."` with `"/dashboard"` and `"/dashboard?..."` respectively.

Specific changes:
- `app/executions/[executionId]/page.tsx:57` — `href="/runs"` → `href="/dashboard"`
- `components/tasks/task-detail-panel.tsx:616` — `href="/runs?tab=executions&task=..."` → `href="/dashboard?tab=executions&task=..."`
- `components/tasks/task-detail-panel.tsx:633` — same pattern
- `components/tasks/task-detail-panel.tsx:649` — `href="/runs?task=..."` → `href="/dashboard?task=..."`
- `components/tasks/task-card.tsx:95` — `href="/runs?task=..."` → `href="/dashboard?task=..."`
- `components/tasks/task-card.tsx:140` — `href="/runs?tab=executions&task=..."` → `href="/dashboard?tab=executions&task=..."`
- `components/tasks/task-list-view.tsx:144` — same pattern
- `components/tasks/task-list-view.tsx:155` — same pattern
- `components/executions/executions-tab.tsx:72` — `router.replace('/runs')` → `router.replace('/dashboard')`

- [ ] **Step 2: Fix 404 route in agent-overview-tab.tsx**

In `frontend/components/agents/agent-overview-tab.tsx:119`, change:
```typescript
href={`/agents/${agentId}/runs/${item.id}`}
```
to:
```typescript
href={`/executions/${item.current_execution_id ?? item.id}`}
```

- [ ] **Step 3: Verify no remaining /runs links**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend
grep -rn 'href.*"/runs' --include="*.tsx" --include="*.ts" . | grep -v node_modules | grep -v ".next" && echo "REMAINING" || echo "Clean"
grep -rn "router.*('/runs" --include="*.tsx" --include="*.ts" . | grep -v node_modules | grep -v ".next" && echo "REMAINING" || echo "Clean"
```

Expected: `Clean` for both.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/executions/[executionId]/page.tsx frontend/components/tasks/task-detail-panel.tsx frontend/components/tasks/task-card.tsx frontend/components/tasks/task-list-view.tsx frontend/components/executions/executions-tab.tsx frontend/components/agents/agent-overview-tab.tsx
git commit -m "fix: replace stale /runs links with /dashboard, fix agent-overview 404 route"
```

---

## Task 8: Type Synchronization + Backend Engine Fix

**Files:**
- Modify: `frontend/types/agent-run.ts:7,59`
- Modify: `frontend/types/tasks.ts:17-19`
- Modify: `backend/app/core/engine/cli_engine.py:22`

- [ ] **Step 1: Add missing trigger_source values**

In `frontend/types/agent-run.ts`, update line 7:
```typescript
  trigger_source: 'task' | 'chat' | 'api' | 'scheduler' | 'comment' | 'mention' | 'copilot'
```

And line 59:
```typescript
  trigger_source: 'task' | 'chat' | 'api' | 'scheduler' | 'comment' | 'mention' | 'copilot'
```

- [ ] **Step 2: Fix current_execution_id comment in tasks.ts**

In `frontend/types/tasks.ts`, replace:
```typescript
  /** Legacy alias: some views use current_execution_id */
  current_execution_id?: string | null
```
with:
```typescript
  /** ID of the current Execution for this task's active AgentRun */
  current_execution_id?: string | null
```

- [ ] **Step 3: Fix engine_kind in cli_engine.py**

In `backend/app/core/engine/cli_engine.py`, change line 22:
```python
    engine_kind = "cli"
```
to:
```python
    engine_kind = "sandbox"
```

- [ ] **Step 4: Commit**

```bash
git add frontend/types/agent-run.ts frontend/types/tasks.ts backend/app/core/engine/cli_engine.py
git commit -m "fix: sync trigger_source enum, fix current_execution_id comment, align engine_kind"
```

---

## Task 9: Duplicate Component Consolidation

**Files:**
- Modify: Multiple graph-builder component imports
- Delete: `frontend/components/editors/graph-builder/components/execution/` directory (all files except `index.ts` which doesn't exist there)

- [ ] **Step 1: Identify graph-builder imports of local execution components**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend
grep -rn "from.*graph-builder/components/execution" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next"
```

For each import found, update the path to use `@/components/execution/` instead.

- [ ] **Step 2: Delete the duplicate directory**

```bash
rm -rf frontend/components/editors/graph-builder/components/execution/
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

- [ ] **Step 4: Commit**

```bash
git add -A frontend/components/editors/graph-builder/components/execution/ frontend/components/
git commit -m "refactor: consolidate duplicate execution components into @/components/execution/"
```

---

## Task 10: Final Verification

- [ ] **Step 1: Full TypeScript check**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend && npx tsc --noEmit --pretty
```

- [ ] **Step 2: Full dangling import check**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend
grep -rn "chatBackend\|eventAdapter\|eventProcessor\|ChatStreamEvent\|ChatWsFrame\|getChatWsClient\|RunSubscriptionManager\|execution_status\|setThreadId\|setRequestId\|setExecutionWs\|executionWs\|requestId.*null\|agentService.*getCachedGraphId" --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next" | grep -v "\.d\.ts"
```

Expected: Empty or only false positives (e.g., `requestId` in unrelated contexts).

- [ ] **Step 3: Backend compile check**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter
python -m py_compile backend/app/core/events/subscribers/persistence.py
python -m py_compile backend/app/services/execution_service.py
python -m py_compile backend/app/api/v1/copilot.py
python -m py_compile backend/app/core/engine/cli_engine.py
echo "All OK"
```

- [ ] **Step 4: Verify no /runs route references remain**

```bash
cd /Users/yuzhenjiang1/Downloads/2024/JoySafeter/frontend
grep -rn '"/runs"' --include="*.ts" --include="*.tsx" . | grep -v node_modules | grep -v ".next" | grep -v "next.config"
```

Expected: Only `next.config.ts` (the redirect rule itself).
