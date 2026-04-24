# Event Architecture Cleanup Design

## Problem

The codebase is mid-migration from a single-tier "Run" model to a two-tier "AgentRun → Execution" architecture with an `ExecutionEventBus`. The audit identified 12 categories of issues: unauthenticated WebSocket connections, broken frame parsing, a dead event processing pipeline, dead code, stale routes, and type mismatches.

## Approach

Three layers, each self-contained and independently verifiable. No old Graph execution engine mode exists — all legacy code paths are dead and will be fully removed.

---

## Layer 1: Protocol Correction + Dead Code Removal

### 1.1 executionAdapter WS Authentication Fix

**Files changed:** `frontend/components/editors/graph-builder/services/executionAdapter.ts`, `frontend/components/editors/graph-builder/stores/execution/executionStore.ts`, `frontend/components/editors/graph-builder/stores/execution/types.ts`

**Problem:** `executionAdapter.subscribeToExecution()` creates a raw `new WebSocket()` with no auth token. The canonical `SharedExecutionWsClient` authenticates via `/api/v1/auth/ws-token`.

**Fix:**
- Remove `subscribeToExecution()` from `executionAdapter`.
- In `executionStore.startExecution()`, replace raw WS usage with `getExecutionWsClient().subscribe(executionId, 0, callbacks)`.
- Replace `ExecutionContext.executionWs: WebSocket | null` with `subscribedExecutionId: string | null`.
- `stopExecution` calls `getExecutionWsClient().unsubscribe(executionId)` instead of `ws.close()`.
- Remove `setExecutionWs` from the store; add `setSubscribedExecutionId`.

### 1.2 WS Frame Protocol Alignment

**Files changed:** `frontend/lib/ws/executions/executionWsClient.ts`, `frontend/lib/ws/executions/types.ts`

**Problem:** Backend sends `execution_completed` and `replay_done` frames that the frontend silently drops. Frontend handles `execution_status` which the backend never sends.

**Fix in `executionWsClient.ts` `handleMessage()`:**
- Add `execution_completed` handler → new `onCompleted` callback.
- Add `replay_done` handler → new `onReplayDone` callback.
- Remove `execution_status` handler branch.

**Fix in `types.ts`:**
- Add `onCompleted?: (frame: ExecutionCompletedFrame) => void` to `ExecutionSubscriptionCallbacks`.
- Add `onReplayDone?: (frame: ExecutionReplayDoneFrame) => void` to `ExecutionSubscriptionCallbacks`.
- Remove `onStatus` from `ExecutionSubscriptionCallbacks`.
- Delete `ExecutionStatusFrame` interface.
- Remove `ExecutionStatusFrame` from `IncomingExecutionWsFrame` union.

### 1.3 Snapshot Frame Parsing Fix

**File changed:** `frontend/components/editors/graph-builder/stores/execution/executionStore.ts`

**Problem:** Snapshot handler reads `frame.payload` which doesn't exist. Real shape is `{ type, execution_id, last_seq, status, events }`.

**Fix:** In the onSnapshot callback, use `frame.status` to update execution status and replay `frame.events` through the new event handler (Layer 2).

### 1.4 Backend Minor Fixes

| File | Line | Fix |
|------|------|-----|
| `backend/app/core/events/subscribers/persistence.py` | 65 | `"execution_completed"` → `ExecutionEventType.EXECUTION_COMPLETED` |
| `backend/app/services/execution_service.py` | 220 | Delete unreachable `return results` |
| `backend/app/websocket/execution_subscription_manager.py` | 12-13 | Delete stale docstring referencing `RunSubscriptionManager` |
| `backend/app/schemas/execution.py` | 67 | Delete duplicate `InjectMessageRequest` |

### 1.5 Dead Code Deletion

| Target | Reason |
|--------|--------|
| `backend/app/schemas/runs.py` | Entire file, zero imports |
| `POST /v1/copilot/stream` endpoint + handler | Legacy SSE, no frontend caller |
| `frontend/lib/ws/chat/` directory (chatWsClient.ts, types.ts, errors.ts, index.ts) | Backend `/ws/chat` endpoint doesn't exist, `getChatWsClient()` never called |
| `frontend/services/chatBackend.ts` | All consumers removed in Layer 2 |
| `handleCopilotEvent` function in `useCopilotWebSocketHandler.ts` | Dead bridge for nonexistent chat WS; only `ChatStreamEvent` import removed |
| `frontend/components/editors/graph-builder/services/eventAdapter.ts` | Old LangGraph event adapter, replaced by native handlers in Layer 2 |
| `frontend/components/editors/graph-builder/services/eventProcessor.ts` | Old event processor, replaced by native handlers in Layer 2 |
| `eventAdapter` and `eventProcessor` exports from `services/index.ts` | Dead re-exports |

**Note:** `useCopilotWebSocketHandler` callbacks (onStatus, onContent, etc.) are **retained** — they are actively used by `useCopilotExecutionBridge` → `CopilotPanel`. Only the `handleCopilotEvent` bridge function and its `ChatStreamEvent` import are removed.

---

## Layer 2: Event Pipeline Rewrite

### 2.1 Native ExecutionEvent Handlers

**File changed:** `frontend/components/editors/graph-builder/stores/execution/executionStore.ts`

Replace the `ChatStreamEvent` conversion + `processEvent()` pipeline with direct `ExecutionEventFrame` handling in the `onEvent` callback from `SharedExecutionWsClient`.

**Mapping table:**

| ExecutionEventType | Action |
|---|---|
| `assistant_text` | If no current thought step, `addStep` with `stepType: 'agent_thought'`; otherwise `appendContent` with `payload.delta` |
| `thinking` | `addStep` with `stepType: 'agent_thought'`, title "Thinking" |
| `tool_use_start` | `addStep` with `stepType: 'tool_execution'`, status `running`; track in local `toolStepMap` by `payload.tool_use_id` |
| `tool_use_end` | `updateStep` matching tool → status success/error; remove from `toolStepMap` |
| `error` | `addStep` with `stepType: 'system_log'`, status `error`; if `payload.code === 'stopped'` → mark stopped |
| `execution_started` | Update workflow step status |
| `execution_completed` | Finalize workflow step → success/failed based on `payload.terminal_status`; set `isExecuting: false` |
| `execution_status_change` | Update local status display |
| `artifact_created` | `addStep` with `stepType: 'artifact'` |
| `approval_requested` | `addInterrupt` |
| `approval_resolved` | `removeInterrupt` |
| `user_message` | noop |
| `copilot_*` events | Not handled in executionStore (handled by `useCopilotExecutionBridge` separately) |

### 2.2 Remove Dead Fields from ExecutionContext

**Files changed:** `stores/execution/types.ts`, `stores/execution/ExecutionManager.ts`, `stores/execution/executionStore.ts`

- Delete `requestId: string | null` from `ExecutionContext` (never set to non-null).
- Delete `threadId: string | null` from `ExecutionContext` (new execution path never produces thread_id).
- Delete `setRequestId` and `setThreadId` from store.
- Delete `executionWs: WebSocket | null` from `ExecutionContext` (replaced by `subscribedExecutionId` in Layer 1).

### 2.3 Remove Old Pipeline Dependencies

From `executionStore.ts`, remove:
- `import type { ChatStreamEvent } from '@/services/chatBackend'`
- `import { processEvent, createEventProcessorContext, type EventProcessorStore } from '../../services/eventProcessor'`
- All `EventProcessorStore` adapter code in `startExecution`
- The `ChatStreamEvent` conversion block (`const chatEvt = { ... } as ChatStreamEvent`)

### 2.4 Remove `agentService.getCachedGraphId()` Fallback

**File:** `executionStore.ts:428`

`const graphId = store.currentGraphId || agentService.getCachedGraphId()` — the fallback to old `agentService` cache is unnecessary. If `currentGraphId` is null, execution should not proceed. Remove the fallback.

---

## Layer 3: Routes + Type Alignment

### 3.1 Route Fixes

**`/runs` links (9 locations):**

All `/runs` links redirect to `/dashboard` losing query params. Fix by pointing to the correct existing pages:

| File | Current | Target |
|------|---------|--------|
| `app/executions/[executionId]/page.tsx:57` | `href="/runs"` | `href="/dashboard"` (back button) |
| `components/tasks/task-detail-panel.tsx:616,633,649` | `href="/runs?tab=executions&task=..."` | `href="/dashboard?tab=executions&task=..."` or appropriate executions route |
| `components/tasks/task-card.tsx:95,140` | `href="/runs?task=..."` | Same fix |
| `components/tasks/task-list-view.tsx:144,155` | `href="/runs?..."` | Same fix |
| `components/executions/executions-tab.tsx:72` | `router.replace('/runs')` | `router.replace('/dashboard')` |

**404 route:**

| File | Current | Fix |
|------|---------|-----|
| `components/agents/agent-overview-tab.tsx:119` | `href={/agents/${agentId}/runs/${item.id}}` | `href={/executions/${item.current_execution_id}}` (linking to the execution detail page that exists) |

### 3.2 Type Synchronization

**`trigger_source` enum:**

Frontend `types/agent-run.ts` line 7 and line 59: add `'comment' | 'mention'` to match backend `TriggerSourceLiteral`.

**`current_execution_id` in tasks:**

`frontend/types/tasks.ts` — the backend `AgentRunResponse` does return `current_execution_id`. Remove the "legacy alias" comment. This field is legitimate in the two-tier model (it's the pointer from AgentRun to its current Execution).

### 3.3 Duplicate Component Consolidation

`frontend/components/execution/` is a thin re-export of `frontend/components/editors/graph-builder/components/execution/` with only import path differences.

**Fix:** Make `frontend/components/execution/` the canonical location. Update graph-builder imports to use `@/components/execution/`. Delete the copies under `graph-builder/components/execution/`.

### 3.4 Backend Engine Registry Naming

| File | Current | Fix |
|------|---------|-----|
| `backend/app/core/engine/cli_engine.py:22` | `engine_kind = "cli"` | Change to `engine_kind = "sandbox"` to match registry key |

The docstring already says `runtime_kind: "sandbox"`. The attribute should match.

---

## Files Deleted (Complete List)

| File | Layer |
|------|-------|
| `backend/app/schemas/runs.py` | L1 |
| `POST /v1/copilot/stream` handler code | L1 |
| `frontend/lib/ws/chat/chatWsClient.ts` | L1 |
| `frontend/lib/ws/chat/types.ts` | L1 |
| `frontend/lib/ws/chat/errors.ts` | L1 |
| `frontend/services/chatBackend.ts` | L1 |
| `frontend/components/editors/graph-builder/services/eventAdapter.ts` | L1 |
| `frontend/components/editors/graph-builder/services/eventProcessor.ts` | L1 |
| `frontend/components/editors/graph-builder/components/execution/` (duplicates) | L3 |

## Files Modified (Key Changes)

| File | Layer | Change |
|------|-------|--------|
| `executionStore.ts` | L1+L2 | Rewrite WS handling, native event handlers, remove old pipeline |
| `executionAdapter.ts` | L1 | Remove `subscribeToExecution()` |
| `types.ts` (execution context) | L1+L2 | Replace `executionWs` with `subscribedExecutionId`, remove `requestId`/`threadId` |
| `executionWsClient.ts` | L1 | Handle `execution_completed`, `replay_done`; remove `execution_status` |
| `ws/executions/types.ts` | L1 | Update callbacks and frame union |
| `useCopilotWebSocketHandler.ts` | L1 | Delete `handleCopilotEvent`, remove `ChatStreamEvent` import |
| `services/index.ts` (graph-builder) | L1 | Remove eventAdapter/eventProcessor exports |
| `persistence.py` | L1 | Use constant instead of string |
| `execution_service.py` | L1 | Delete unreachable code |
| `execution_subscription_manager.py` | L1 | Delete stale docstring |
| `schemas/execution.py` | L1 | Delete duplicate class |
| `types/agent-run.ts` | L3 | Add `comment`/`mention` to trigger_source |
| `types/tasks.ts` | L3 | Remove "legacy alias" comment |
| 9 component files with `/runs` links | L3 | Point to correct routes |
| `agent-overview-tab.tsx` | L3 | Fix 404 route |
| `cli_engine.py` | L3 | `engine_kind = "sandbox"` |

---

## Post-Deletion Flow Verification

After each layer, verify these end-to-end flows are unbroken:

### Flow A: Graph Builder Execution (Layer 1+2 critical path)

```
User clicks Run in Graph Builder
  → executionStore.startExecution(input)
    → agentService.get(agentId) → get active_release_id
    → executionAdapter.startRun({ releaseId, prompt, workspaceId })
      → POST /v1/runs → returns { id, current_execution_id, status }
    → getExecutionWsClient().subscribe(executionId, 0, callbacks)
      → WS /ws/executions (authenticated) → sends { type: 'subscribe', execution_id }
      → receives 'snapshot' frame → update status from frame.status
      → receives 'event' frames → native handler maps to ExecutionStep
      → receives 'execution_completed' → finalize, set isExecuting: false
      → receives 'replay_done' → catch-up complete
    → User clicks Stop
      → executionAdapter.cancelRun(runId) → POST /v1/runs/{id}/cancel
      → getExecutionWsClient().unsubscribe(executionId)
```

### Flow B: Copilot Panel Execution (must remain intact)

```
User sends message in CopilotPanel
  → useCopilotActions.handleSend()
    → copilotService.dispatchRun({ graphId, prompt, ... })
      → POST /v1/copilot/run → returns { run_id, execution_id }
    → setSession(runId, executionId)
  → useCopilotExecutionBridge subscribes to executionId
    → useExecutionStream → getExecutionWsClient().subscribe(executionId, ...)
    → receives copilot_* events
    → dispatches to callbacks from useCopilotWebSocketHandler:
      onStatus, onContent, onThoughtStep, onToolCall, onToolResult, onResult, onError, onDone
    → callbacks update CopilotState (streaming, messages, etc.)
  → onDone → clearSession, invalidate queries
```

### Flow C: Execution Detail Page (read-only, verify not broken by route changes)

```
User navigates to /executions/{executionId}
  → page fetches execution via agentRunService.getExecution(id)
  → useExecutionStream subscribes for live updates
  → ExecutionTimeline renders events
  → Back button → href="/dashboard" (was /runs)
```

### Flow D: Task → Execution Navigation (verify route fixes)

```
User views task card/detail
  → "View Executions" link → /dashboard?tab=executions&task={id} (was /runs?...)
  → Dashboard receives query params and filters correctly
```

### Verification Method

After each layer:
1. TypeScript compilation: `npx tsc --noEmit` — zero errors
2. Grep for dangling imports: any file importing deleted modules must be caught
3. Search for string references to deleted file paths
4. Backend: `python -m py_compile` on changed files
