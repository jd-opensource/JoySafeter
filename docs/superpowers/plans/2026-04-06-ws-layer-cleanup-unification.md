# WebSocket Layer Cleanup & Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify frontend WS clients into a shared base class, clean up dead code, standardize auth and naming across the communication layer.

**Architecture:** Extract `BaseWsClient` abstract class from duplicated chat/runs/notification WS clients. Migrate each client incrementally. Remove legacy backend endpoints and protocol tombstones. Unify auth to ws-token for all WS connections.

**Tech Stack:** TypeScript (frontend), Python/FastAPI (backend), WebSocket

**Spec:** `docs/superpowers/specs/2026-04-06-ws-layer-cleanup-unification-design.md`

---

### Task 1: Add RECONNECT constants to shared constants file

**Files:**
- Modify: `frontend/lib/ws/constants.ts`

- [ ] **Step 1: Add RECONNECT constants**

```typescript
// Add after the HEARTBEAT export in frontend/lib/ws/constants.ts

/** Reconnect configuration */
export const RECONNECT = {
  /** Maximum delay between reconnect attempts (ms) */
  MAX_DELAY_MS: 15_000,
  /** Default max reconnect attempts before giving up */
  DEFAULT_MAX_ATTEMPTS: 20,
} as const
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/ws/constants.ts
git commit -m "refactor: add RECONNECT constants to shared WS constants"
```

---

### Task 2: Create BaseWsClient abstract class

**Files:**
- Create: `frontend/lib/ws/base/BaseWsClient.ts`

- [ ] **Step 1: Create the base directory and file**

Create `frontend/lib/ws/base/BaseWsClient.ts` with the full abstract class:

```typescript
'use client'

import { HEARTBEAT, RECONNECT, UNRECOVERABLE_CLOSE_CODES, WS_CLOSE_CODE } from '../constants'

export interface BaseConnectionState {
  isConnected: boolean
  authExpired?: boolean
}

export type ReconnectStrategy = 'exponential' | 'fixed'

export interface WsClientConfig {
  /** null = unlimited reconnect attempts */
  maxReconnectAttempts: number | null
  maxReconnectDelayMs: number
  reconnectStrategy: ReconnectStrategy
  /** Only used when reconnectStrategy='fixed' */
  fixedReconnectIntervalMs: number
  pingIntervalMs: number
  pongTimeoutMs: number
  /** Logging prefix, e.g. "[ChatWS]" */
  name: string
}

const DEFAULT_CONFIG: WsClientConfig = {
  maxReconnectAttempts: RECONNECT.DEFAULT_MAX_ATTEMPTS,
  maxReconnectDelayMs: RECONNECT.MAX_DELAY_MS,
  reconnectStrategy: 'exponential',
  fixedReconnectIntervalMs: 3000,
  pingIntervalMs: HEARTBEAT.PING_INTERVAL_MS,
  pongTimeoutMs: HEARTBEAT.PONG_TIMEOUT_MS,
  name: '[WS]',
}

export abstract class BaseWsClient<TState extends BaseConnectionState = BaseConnectionState> {
  protected ws: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private lastPongTime = Date.now()
  protected isDisposed = false
  private state: TState
  private stateListeners = new Set<(state: TState) => void>()
  protected readonly config: WsClientConfig

  constructor(config?: Partial<WsClientConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    this.state = this.createInitialState()
  }

  async connect(): Promise<void> {
    if (this.isDisposed) {
      this.isDisposed = false
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      return Promise.resolve()
    }
    if (this.connectPromise) {
      return this.connectPromise
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    this.connectPromise = this.getWsUrl()
      .then(
        (wsUrl) =>
          new Promise<void>((resolve, reject) => {
            const ws = new WebSocket(wsUrl)
            this.ws = ws

            ws.onopen = () => {
              this.reconnectAttempts = 0
              this.setConnectionState(true)
              this.startHeartbeat()
              this.connectPromise = null
              resolve()
            }

            ws.onmessage = (event) => {
              try {
                const parsed = JSON.parse(event.data)
                if (parsed.type === 'pong') {
                  this.lastPongTime = Date.now()
                  return
                }
                this.handleMessage(parsed)
              } catch {
                this.onParseError()
              }
            }

            ws.onerror = () => {
              this.setConnectionState(false)
              if (this.connectPromise) {
                this.connectPromise = null
                reject(this.createConnectionError('WebSocket connection failed'))
              }
            }

            ws.onclose = (event) => {
              this.stopHeartbeat()
              this.ws = null

              if (this.connectPromise) {
                this.connectPromise = null
                reject(this.createConnectionError(`WebSocket connection failed (${event.code})`))
              }

              if (event.code === WS_CLOSE_CODE.UNAUTHORIZED) {
                this.state = { ...this.state, isConnected: false, authExpired: true }
                this.stateListeners.forEach((l) => l(this.state))
                this.onAuthExpired()
                return
              }

              this.setConnectionState(false)

              if (event.code === WS_CLOSE_CODE.NORMAL || this.isDisposed) {
                return
              }

              this.onUnexpectedClose()

              if (UNRECOVERABLE_CLOSE_CODES.includes(event.code as (typeof UNRECOVERABLE_CLOSE_CODES)[number])) {
                return
              }

              this.scheduleReconnect()
            }
          }),
      )
      .catch((err) => {
        this.connectPromise = null
        throw err
      })

    return this.connectPromise
  }

  disconnect(): void {
    this.isDisposed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.stopHeartbeat()
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onerror = null
      this.ws.onclose = null
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close()
      }
      this.ws = null
    }
    this.connectPromise = null
    this.setConnectionState(false)
    this.onDispose()
  }

  getConnectionState(): TState {
    return this.state
  }

  subscribeConnectionState(listener: (state: TState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => {
      this.stateListeners.delete(listener)
    }
  }

  protected sendFrame(payload: Record<string, unknown>): void {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      throw this.createConnectionError('WebSocket not connected')
    }
    this.ws.send(JSON.stringify(payload))
  }

  protected setConnectionState(isConnected: boolean, extra?: Partial<TState>): void {
    this.state = { ...this.state, isConnected, ...extra }
    this.stateListeners.forEach((listener) => listener(this.state))
  }

  // === Abstract methods — subclasses MUST implement ===

  protected abstract getWsUrl(): Promise<string>
  protected abstract handleMessage(data: unknown): void
  protected abstract createInitialState(): TState

  // === Optional hooks — subclasses MAY override ===

  /** Called after a successful reconnect. Use to re-subscribe, etc. */
  protected onReconnected(): void {}
  /** Called when max reconnect attempts are exhausted. */
  protected onReconnectExhausted(): void {}
  /** Called during disconnect() for subclass cleanup. */
  protected onDispose(): void {}
  /** Called on auth expiry (close code 4001). */
  protected onAuthExpired(): void {}
  /** Called on unexpected close before reconnect scheduling. */
  protected onUnexpectedClose(): void {}
  /** Called when a message fails to parse. */
  protected onParseError(): void {}
  /** Override to return typed errors (e.g. ChatWsError). */
  protected createConnectionError(message: string): Error {
    return new Error(message)
  }

  // === Private internals ===

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.lastPongTime = Date.now()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return
      if (Date.now() - this.lastPongTime > this.config.pongTimeoutMs) {
        console.warn(`${this.config.name} Heartbeat timeout — no pong in ${this.config.pongTimeoutMs}ms, reconnecting`)
        this.ws.close()
        return
      }
      this.ws.send(JSON.stringify({ type: 'ping' }))
    }, this.config.pingIntervalMs)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.isDisposed || this.reconnectTimer) return

    if (
      this.config.maxReconnectAttempts !== null &&
      this.reconnectAttempts >= this.config.maxReconnectAttempts
    ) {
      console.error(`${this.config.name} Max reconnect attempts reached`)
      this.onReconnectExhausted()
      return
    }

    const delay =
      this.config.reconnectStrategy === 'fixed'
        ? this.config.fixedReconnectIntervalMs
        : Math.min(1000 * 2 ** this.reconnectAttempts, this.config.maxReconnectDelayMs)

    this.reconnectAttempts += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.connect()
        .then(() => this.onReconnected())
        .catch(() => {})
    }, delay)
  }
}
```

- [ ] **Step 2: Export from an index file**

Create `frontend/lib/ws/base/index.ts`:

```typescript
export { BaseWsClient } from './BaseWsClient'
export type { BaseConnectionState, WsClientConfig, ReconnectStrategy } from './BaseWsClient'
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/ws/base/
git commit -m "feat: add BaseWsClient abstract class for shared WS lifecycle"
```

---

### Task 3: Migrate ChatWsClient to extend BaseWsClient

**Files:**
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`
- Modify: `frontend/lib/ws/chat/types.ts` (rename `dispose` → `disconnect`)
- Modify: `frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts` (update `.dispose()` → `.disconnect()`)
- Modify: `frontend/app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts` (update `.dispose()` → `.disconnect()`)

- [ ] **Step 1: Update ChatWsClient interface — rename dispose to disconnect**

In `frontend/lib/ws/chat/types.ts`, change line 101:

```typescript
// Old:
  dispose(): void
// New:
  disconnect(): void
```

- [ ] **Step 2: Rewrite SharedChatWsClient to extend BaseWsClient**

Replace the entire `frontend/lib/ws/chat/chatWsClient.ts` with:

```typescript
'use client'

import { generateUUID } from '@/lib/utils/uuid'
import { getWsChatUrl } from '@/lib/utils/wsUrl'
import type { ChatStreamEvent } from '@/services/chatBackend'

import { BaseWsClient } from '../base'
import type { BaseConnectionState } from '../base'
import { ChatWsError } from './errors'
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

interface PendingRequest {
  requestId: string
  threadId?: string
  onEvent?: (evt: ChatStreamEvent) => void
  onAccepted?: (evt: IncomingChatAcceptedEvent) => void
  resolve: (value: ChatTerminalResult) => void
  reject: (error: Error) => void
}

class SharedChatWsClient extends BaseWsClient<ConnectionState> implements ChatWsClient {
  private static readonly MAX_PARSE_FAILURES = 10
  private consecutiveParseFailures = 0
  private pending = new Map<string, PendingRequest>()
  private threadToRequest = new Map<string, string>()

  constructor() {
    super({
      maxReconnectAttempts: 20,
      name: '[ChatWS]',
    })
  }

  protected createInitialState(): ConnectionState {
    return { isConnected: false }
  }

  protected async getWsUrl(): Promise<string> {
    return getWsChatUrl()
  }

  protected handleMessage(evt: IncomingChatWsEvent): void {
    this.consecutiveParseFailures = 0
    this.handleInboundMessage(evt)
  }

  protected override onParseError(): void {
    this.consecutiveParseFailures++
    console.warn(`[ChatWS] Malformed frame (${this.consecutiveParseFailures} consecutive)`)
    if (this.consecutiveParseFailures >= SharedChatWsClient.MAX_PARSE_FAILURES) {
      console.error('[ChatWS] Too many consecutive parse failures, reconnecting')
      this.consecutiveParseFailures = 0
      this.ws?.close()
    }
  }

  protected override onAuthExpired(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Authentication expired'))
  }

  protected override onUnexpectedClose(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'WebSocket disconnected'))
  }

  protected override onReconnectExhausted(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Connection lost. Please refresh the page.'))
  }

  protected override onDispose(): void {
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Chat session closed'))
  }

  protected override createConnectionError(message: string): Error {
    return new ChatWsError('WS_CONNECTION_FAILED', message)
  }

  // === Chat-specific public API ===

  async sendChat(params: ChatSendParams): Promise<ChatTerminalResult> {
    const message = params.input.message
    if (!message.trim()) {
      throw new Error('Message cannot be empty')
    }
    await this.connect()
    const requestId = params.requestId || generateUUID()
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId || undefined,
        onEvent: params.onEvent,
        onAccepted: params.onAccepted,
        resolve,
        reject,
      })
      if (params.threadId) {
        this.threadToRequest.set(params.threadId, requestId)
      }

      try {
        this.sendFrame({
          type: 'chat.start',
          request_id: requestId,
          thread_id: params.threadId || null,
          graph_id: params.graphId || null,
          input: serializeInput(params.input),
          extension: serializeExtension(params.extension),
          metadata: params.metadata || {},
        })
      } catch (error) {
        this.clearPending(requestId)
        reject(error instanceof Error ? error : new ChatWsError('WS_NOT_CONNECTED', 'WebSocket not connected'))
      }
    })
  }

  async sendResume(params: ChatResumeParams): Promise<ChatTerminalResult> {
    await this.connect()
    const requestId = params.requestId || generateUUID()

    return new Promise((resolve, reject) => {
      this.pending.set(requestId, {
        requestId,
        threadId: params.threadId,
        onEvent: params.onEvent,
        onAccepted: params.onAccepted,
        resolve,
        reject,
      })
      this.threadToRequest.set(params.threadId, requestId)

      try {
        this.sendFrame({
          type: 'chat.resume',
          request_id: requestId,
          thread_id: params.threadId,
          command: params.command,
        })
      } catch (error) {
        this.clearPending(requestId)
        reject(error instanceof Error ? error : new ChatWsError('WS_NOT_CONNECTED', 'WebSocket not connected'))
      }
    })
  }

  stopByThreadId(threadId: string): void {
    const requestId = this.threadToRequest.get(threadId)
    if (!requestId) return
    this.stopByRequestId(requestId)
  }

  stopByRequestId(requestId: string): void {
    if (!requestId) return
    try {
      this.sendFrame({ type: 'chat.stop', request_id: requestId })
    } catch {
      // Ignore stop failures
    }
  }

  // === Private helpers ===

  private handleInboundMessage(evt: IncomingChatWsEvent) {
    const type: string | undefined = evt.type
    if (!type) return

    const requestId = evt.request_id
    if (type === 'ws_error') {
      if (requestId) {
        this.rejectPending(
          requestId,
          new ChatWsError('WS_PROTOCOL_ERROR', evt.message || 'WebSocket protocol error', { evt }),
        )
      }
      return
    }

    if (!requestId) return
    const pending = this.pending.get(requestId)
    if (!pending) return

    if (evt.thread_id) {
      pending.threadId = evt.thread_id
      this.threadToRequest.set(evt.thread_id, requestId)
    }

    if (type === 'accepted') {
      pending.onAccepted?.(evt as IncomingChatAcceptedEvent)
      return
    }

    pending.onEvent?.(evt as ChatStreamEvent)

    if (type === 'interrupt') {
      this.resolvePending(requestId, 'interrupt')
      return
    }
    if (type === 'done') {
      this.resolvePending(requestId, 'done')
      return
    }
    if (type === 'error') {
      const message = (evt.data as { message?: string } | undefined)?.message || 'Unknown error'
      if (message === 'Stream stopped' || message.includes('stopped')) {
        this.resolvePending(requestId, 'stopped')
      } else {
        this.rejectPending(requestId, new ChatWsError('CHAT_EXECUTION_ERROR', message, { evt }))
      }
    }
  }

  private resolvePending(requestId: string, terminal: ChatTerminalResult['terminal']) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.clearPending(requestId)
    pending.resolve({ requestId, threadId: pending.threadId, terminal })
  }

  private rejectPending(requestId: string, error: Error) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.clearPending(requestId)
    pending.reject(error)
  }

  private clearPending(requestId: string) {
    const pending = this.pending.get(requestId)
    if (!pending) return
    this.pending.delete(requestId)
    if (pending.threadId) {
      this.threadToRequest.delete(pending.threadId)
    }
  }

  private rejectAllPending(error: Error) {
    const requestIds = Array.from(this.pending.keys())
    requestIds.forEach((requestId) => this.rejectPending(requestId, error))
  }
}

function serializeInput(input: ChatSendParams['input']): Record<string, unknown> {
  const result: Record<string, unknown> = { message: input.message }
  if (input.files && input.files.length > 0) {
    result.files = input.files
  }
  if (input.model) {
    result.model = input.model
  }
  return result
}

function serializeExtension(extension?: SkillCreatorExtension | ChatExtension | CopilotExtension | null): Record<string, unknown> | null {
  if (!extension) return null
  if (extension.kind === 'skill_creator') {
    return { kind: extension.kind, run_id: extension.runId ?? null, edit_skill_id: extension.editSkillId ?? null }
  }
  if (extension.kind === 'chat') {
    return { kind: extension.kind, run_id: extension.runId ?? null }
  }
  if (extension.kind === 'copilot') {
    return {
      kind: extension.kind, run_id: extension.runId ?? null,
      graph_context: extension.graphContext,
      conversation_history: extension.conversationHistory,
      mode: extension.mode,
    }
  }
  return null
}

let singleton: SharedChatWsClient | null = null

export function getChatWsClient(): ChatWsClient {
  if (!singleton) {
    singleton = new SharedChatWsClient()
  }
  return singleton
}
```

- [ ] **Step 3: Update test files — rename .dispose() to .disconnect()**

In `frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts` line 94, change:
```typescript
// Old:
getChatWsClient().dispose()
// New:
getChatWsClient().disconnect()
```

In `frontend/app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts` line 80, change:
```typescript
// Old:
getChatWsClient().dispose()
// New:
getChatWsClient().disconnect()
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 5: Run existing chat WS tests**

Run: `cd frontend && npx jest --testPathPattern="useChatWebSocket|workspaceChatWsService" --no-coverage 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/ws/chat/ frontend/app/chat/hooks/__tests__/useChatWebSocket.test.ts "frontend/app/workspace/[workspaceId]/[agentId]/services/__tests__/workspaceChatWsService.test.ts"
git commit -m "refactor: migrate ChatWsClient to extend BaseWsClient"
```

---

### Task 4: Migrate RunWsClient to extend BaseWsClient

**Files:**
- Modify: `frontend/lib/ws/runs/runWsClient.ts`

- [ ] **Step 1: Rewrite SharedRunWsClient to extend BaseWsClient**

Replace the entire `frontend/lib/ws/runs/runWsClient.ts` with:

```typescript
'use client'

import { getWsRunsUrl } from '@/lib/utils/wsUrl'

import { BaseWsClient } from '../base'
import type {
  IncomingRunWsFrame,
  RunConnectionState,
  RunSubscriptionCallbacks,
  RunWsClient,
} from './types'

interface RunSubscriptionState {
  afterSeq: number
  callbacks: RunSubscriptionCallbacks
}

class SharedRunWsClient extends BaseWsClient<RunConnectionState> implements RunWsClient {
  private subscriptions = new Map<string, RunSubscriptionState>()

  constructor() {
    super({
      maxReconnectAttempts: null, // unlimited
      name: '[RunsWS]',
    })
  }

  protected createInitialState(): RunConnectionState {
    return { isConnected: false }
  }

  protected async getWsUrl(): Promise<string> {
    return getWsRunsUrl()
  }

  protected handleMessage(frame: IncomingRunWsFrame): void {
    if (frame.type === 'ws_error') {
      const targetRunId = 'run_id' in frame ? (frame as { run_id?: string }).run_id : undefined
      if (targetRunId) {
        const sub = this.subscriptions.get(targetRunId)
        sub?.callbacks.onError?.(frame.message)
      } else {
        this.subscriptions.forEach(({ callbacks }) => callbacks.onError?.(frame.message))
      }
      return
    }

    const subscription = 'run_id' in frame ? this.subscriptions.get(frame.run_id) : undefined
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
    if (frame.type === 'replay_done') {
      subscription.afterSeq = Math.max(subscription.afterSeq, frame.last_seq)
      callbacks.onReplayDone?.(frame)
    }
    if (frame.type === 'run_status') callbacks.onStatus?.(frame)
  }

  protected override onReconnected(): void {
    const current = Array.from(this.subscriptions.entries())
    current.forEach(([runId, subscription]) => {
      try {
        this.sendFrame({
          type: 'subscribe',
          run_id: runId,
          after_seq: subscription.afterSeq,
        })
      } catch {
        // Next reconnect or caller recovery can re-subscribe.
      }
    })
  }

  // === Run-specific public API ===

  async subscribe(runId: string, afterSeq: number, callbacks?: RunSubscriptionCallbacks): Promise<void> {
    await this.connect()
    const existing = this.subscriptions.get(runId)
    const normalizedAfterSeq = existing ? Math.max(existing.afterSeq, afterSeq) : afterSeq
    this.subscriptions.set(runId, {
      afterSeq: normalizedAfterSeq,
      callbacks: callbacks || {},
    })
    this.sendFrame({
      type: 'subscribe',
      run_id: runId,
      after_seq: normalizedAfterSeq,
    })
  }

  unsubscribe(runId: string): void {
    this.subscriptions.delete(runId)
    try {
      this.sendFrame({ type: 'unsubscribe', run_id: runId })
    } catch {
      // Ignore connection errors on unsubscribe.
    }
  }
}

let singleton: SharedRunWsClient | null = null

export function getRunWsClient(): RunWsClient {
  if (!singleton) {
    singleton = new SharedRunWsClient()
  }
  return singleton
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/ws/runs/runWsClient.ts
git commit -m "refactor: migrate RunWsClient to extend BaseWsClient"
```

---

### Task 5: Migrate NotificationWsClient to extend BaseWsClient + unify auth

**Files:**
- Create: `frontend/lib/ws/notifications/NotificationWsClient.ts`
- Modify: `frontend/hooks/use-notification-websocket.ts`
- Modify: `frontend/lib/utils/wsUrl.ts` (add `getWsNotificationUrl`)

**Prerequisites:** Verify backend notification endpoint responds to pings with pongs. Check `backend/app/main.py` `_run_notification_loop` — confirmed: lines 310-314 handle `"ping"` → sends `PONG`. No backend changes needed.

**Behavioral note:** The `autoReconnect`, `reconnectInterval`, `maxReconnectAttempts` options are dropped — reconnection is now always enabled via `NotificationWsClient`'s fixed config. Verify no caller passes `autoReconnect: false` before proceeding:

Run: `cd frontend && grep -rn "autoReconnect" --include="*.ts" --include="*.tsx" .`

- [ ] **Step 1: Add getWsNotificationUrl to wsUrl.ts**

Add at the end of `frontend/lib/utils/wsUrl.ts`:

```typescript
/** Fetch a short-lived WS token from the backend and return a ready-to-use notification WS URL. */
export async function getWsNotificationUrl(): Promise<string> {
  return getWsTokenUrl('/ws/notifications')
}
```

- [ ] **Step 2: Create NotificationWsClient class**

Create `frontend/lib/ws/notifications/NotificationWsClient.ts`:

```typescript
'use client'

import { getWsNotificationUrl } from '@/lib/utils/wsUrl'

import { BaseWsClient } from '../base'
import type { BaseConnectionState } from '../base'

export interface NotificationMessage {
  type: string
  data?: any
  message?: string
  timestamp?: string
}

export type NotificationHandler = (notification: NotificationMessage) => void

export class NotificationWsClient extends BaseWsClient<BaseConnectionState> {
  private notificationHandler: NotificationHandler | null = null

  constructor() {
    super({
      maxReconnectAttempts: 10,
      reconnectStrategy: 'fixed',
      fixedReconnectIntervalMs: 3000,
      name: '[NotifWS]',
    })
  }

  protected createInitialState(): BaseConnectionState {
    return { isConnected: false }
  }

  protected async getWsUrl(): Promise<string> {
    return getWsNotificationUrl()
  }

  protected handleMessage(data: unknown): void {
    const notification = data as NotificationMessage
    this.notificationHandler?.(notification)
  }

  setNotificationHandler(handler: NotificationHandler | null): void {
    this.notificationHandler = handler
  }
}
```

- [ ] **Step 3: Rewrite use-notification-websocket.ts to use NotificationWsClient**

Replace the entire `frontend/hooks/use-notification-websocket.ts` with:

```typescript
'use client'

import { useEffect, useRef, useCallback, useState } from 'react'

import { NotificationWsClient } from '@/lib/ws/notifications/NotificationWsClient'
import type { NotificationMessage } from '@/lib/ws/notifications/NotificationWsClient'

export type { NotificationMessage } from '@/lib/ws/notifications/NotificationWsClient'

export enum NotificationType {
  PING = 'ping',
  PONG = 'pong',
  CONNECTED = 'connected',
}

export interface UseNotificationWebSocketOptions {
  userId: string | null | undefined
  onNotification?: (notification: NotificationMessage) => void
  autoReconnect?: boolean
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

export function useNotificationWebSocket(options: UseNotificationWebSocketOptions) {
  const { userId, onNotification } = options
  const clientRef = useRef<NotificationWsClient | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [lastNotification, setLastNotification] = useState<NotificationMessage | null>(null)

  const onNotificationRef = useRef(onNotification)
  useEffect(() => {
    onNotificationRef.current = onNotification
  }, [onNotification])

  const getClient = useCallback(() => {
    if (!clientRef.current) {
      clientRef.current = new NotificationWsClient()
    }
    return clientRef.current
  }, [])

  const cleanup = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect()
      clientRef.current = null
    }
    setIsConnected(false)
  }, [])

  const connect = useCallback(() => {
    if (!userId) return
    const client = getClient()

    client.setNotificationHandler((notification) => {
      setLastNotification(notification)
      onNotificationRef.current?.(notification)
    })

    client.subscribeConnectionState((state) => {
      setIsConnected(state.isConnected)
    })

    void client.connect().catch(() => {})
  }, [userId, getClient])

  useEffect(() => {
    if (userId) {
      connect()
    } else {
      cleanup()
    }
    return () => cleanup()
  }, [userId, connect, cleanup])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && userId) {
        const client = clientRef.current
        if (!client || !client.getConnectionState().isConnected) {
          connect()
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [userId, connect])

  return {
    isConnected,
    lastNotification,
    reconnect: connect,
    disconnect: cleanup,
  }
}

export default useNotificationWebSocket
```

**Note:** The hook no longer accepts `autoReconnect`, `reconnectInterval`, `maxReconnectAttempts` as config — these are now fixed in `NotificationWsClient`'s constructor. Check if any caller passes custom values; if so, adjust. The hook interface is preserved for backward compat (the params are in the options type but unused).

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/ws/notifications/ frontend/hooks/use-notification-websocket.ts frontend/lib/utils/wsUrl.ts
git commit -m "refactor: migrate NotificationWsClient to BaseWsClient + unify auth via ws-token"
```

---

### Task 6: Constants cleanup — remove duplicates and NO_RECONNECT_CLOSE_CODES

**Files:**
- Modify: `frontend/lib/ws/constants.ts` (delete `NO_RECONNECT_CLOSE_CODES`)

Now that `use-notification-websocket.ts` no longer imports `NO_RECONNECT_CLOSE_CODES`, it's safe to remove.

- [ ] **Step 1: Verify no remaining imports of NO_RECONNECT_CLOSE_CODES**

Run: `cd frontend && grep -r "NO_RECONNECT_CLOSE_CODES" --include="*.ts" --include="*.tsx" .`
Expected: Only `lib/ws/constants.ts` itself (the definition)

- [ ] **Step 2: Remove NO_RECONNECT_CLOSE_CODES from constants.ts**

Delete lines 28-32 from `frontend/lib/ws/constants.ts`:

```typescript
// DELETE THIS BLOCK:
/** Close codes where reconnection should be skipped (normal + unrecoverable) */
export const NO_RECONNECT_CLOSE_CODES = [
  WS_CLOSE_CODE.NORMAL,
  ...UNRECOVERABLE_CLOSE_CODES,
] as const
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/ws/constants.ts
git commit -m "refactor: remove NO_RECONNECT_CLOSE_CODES (superseded by BaseWsClient)"
```

---

### Task 7: Remove dead `POST /copilot/actions` backend endpoint

**Files:**
- Modify: `backend/app/api/v1/graphs.py` (delete lines 649-683)

- [ ] **Step 1: Verify no frontend callers exist**

Run: `cd frontend && grep -r "copilot/actions" --include="*.ts" --include="*.tsx" .`
Expected: No matches (confirmed: only WS path is used)

- [ ] **Step 2: Delete the endpoint function**

In `backend/app/api/v1/graphs.py`, delete the entire `generate_graph_actions` function (lines 649-683, the `@router.post("/copilot/actions", response_model=CopilotResponse)` endpoint).

**Do NOT delete** the `CopilotResponse` import or model — it's still used by `CopilotService`.

- [ ] **Step 3: Clean up unused imports**

After deleting the endpoint, check if `CopilotRequest` is still imported and used elsewhere in the same file. If not, remove the `CopilotRequest` import from the `from app.core.copilot import (...)` block at lines 19-22. Keep `CopilotResponse` only if other code in the file uses it; otherwise remove it too from this file's imports (the model itself lives in `app.core.copilot` and is used by the service layer).

- [ ] **Step 4: Verify backend starts**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/graphs.py
git commit -m "fix: remove dead POST /copilot/actions endpoint (migrated to WS)"
```

---

### Task 8: Remove legacy protocol tombstones from chat_protocol.py

**Files:**
- Modify: `backend/app/websocket/chat_protocol.py`
- Modify: `backend/app/websocket/chat_ws_handler.py` (remove `"resume"`/`"stop"` aliases)

**Note:** Spec mentions simplifying `RESERVED_METADATA_KEYS` after removing `"chat"` — this is intentionally skipped because `RESERVED_METADATA_KEYS` is still used for validating `chat.start` frames (line 109 of `chat_protocol.py`), not just the `"chat"` tombstone.

- [ ] **Step 1: Clean up ALLOWED_CLIENT_FRAME_TYPES**

In `backend/app/websocket/chat_protocol.py`, replace the `ALLOWED_CLIENT_FRAME_TYPES` set (lines 10-18):

```python
# Old:
ALLOWED_CLIENT_FRAME_TYPES = {
    "ping",
    "chat",
    "chat.start",
    "chat.resume",
    "chat.stop",
    "resume",
    "stop",
}

# New:
ALLOWED_CLIENT_FRAME_TYPES = {
    "ping",
    "chat.start",
    "chat.resume",
    "chat.stop",
}
```

- [ ] **Step 2: Remove the "chat" tombstone rejection block**

In `backend/app/websocket/chat_protocol.py`, delete lines 92-96:

```python
# DELETE:
    if frame_type == "chat":
        raise ChatProtocolError(
            "legacy metadata control fields are no longer supported",
            request_id=_coerce_request_id(frame.get("request_id")),
        )
```

- [ ] **Step 3: Remove "resume"/"stop" aliases from chat_ws_handler.py**

In `backend/app/websocket/chat_ws_handler.py`, find the dispatch around lines 126-131 and update:

```python
# Old:
        if frame_type in {"chat.resume", "resume"}:
            await self._handle_resume(parsed_frame)
            return
        if frame_type in {"chat.stop", "stop"}:
            await self._handle_stop(parsed_frame)
            return

# New:
        if frame_type == "chat.resume":
            await self._handle_resume(parsed_frame)
            return
        if frame_type == "chat.stop":
            await self._handle_stop(parsed_frame)
            return
```

- [ ] **Step 4: Verify frontend only sends canonical frame types**

Run: `cd frontend && grep -rn '"resume"\|"stop"\|type.*resume\|type.*stop' --include="*.ts" lib/ws/chat/`
Expected: Only `chat.resume` and `chat.stop` — no bare `resume` or `stop`.

- [ ] **Step 5: Verify backend starts**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/websocket/chat_protocol.py backend/app/websocket/chat_ws_handler.py
git commit -m "fix: remove legacy 'chat', 'resume', 'stop' frame type aliases from protocol"
```

---

### Task 9: Remove unused axios dependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Verify no imports of axios exist**

Run: `cd frontend && grep -r "from 'axios'\|require.*axios\|import.*axios" --include="*.ts" --include="*.tsx" .`
Expected: No matches

- [ ] **Step 2: Remove axios**

Run: `cd frontend && bun remove axios`
(If bun is not available: `npm uninstall axios`)

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/bun.lock
git commit -m "chore: remove unused axios dependency"
```

---

### Task 10: Rename SSE-era identifiers to WS semantics

**Files:**
- Modify: `frontend/services/chatBackend.ts` (rename `StreamEventEnvelope` → `ChatWsFrame`)
- Modify: `backend/app/websocket/chat_ws_handler.py` (rename `_parse_sse_event` → `_parse_stream_event`, `_send_event_from_sse` → `_send_stream_event`)
- Modify: `backend/app/websocket/chat_turn_executor.py` (update call sites)

- [ ] **Step 1: Rename StreamEventEnvelope in chatBackend.ts**

In `frontend/services/chatBackend.ts`:
- Find the type definition `export type StreamEventEnvelope = ...` (around line 243)
- Rename to `export type ChatWsFrame = ...`
- Find the re-alias `export type ChatStreamEvent = StreamEventEnvelope` (around line 272)
- Change to `export type ChatStreamEvent = ChatWsFrame`
- Search the same file for any other references to `StreamEventEnvelope` and rename them

Verify no other frontend file imports `StreamEventEnvelope` directly:

Run: `cd frontend && grep -r "StreamEventEnvelope" --include="*.ts" --include="*.tsx" .`
Expected: Only `services/chatBackend.ts`

- [ ] **Step 2: Rename backend methods in chat_ws_handler.py**

In `backend/app/websocket/chat_ws_handler.py`:
- Find `_send_event_from_sse` (around line 547) → rename to `_send_stream_event`
- Find `_parse_sse_event` (around line 568) → rename to `_parse_stream_event`
- Update the internal call from `_send_event_from_sse` to `_parse_sse_event` → `_send_stream_event` to `_parse_stream_event`
- Update any SSE-referencing comments in these methods to say "stream event"

- [ ] **Step 3: Update call sites in chat_turn_executor.py**

In `backend/app/websocket/chat_turn_executor.py`, find and replace all occurrences:
- `handler._send_event_from_sse` → `handler._send_stream_event` (at lines ~258, 289, 614, 628)
- `handler._parse_sse_event` → `handler._parse_stream_event` (if any direct calls)

Run: `cd backend && grep -rn "_send_event_from_sse\|_parse_sse_event" app/`
Expected: No remaining references after the rename

- [ ] **Step 4: Verify TypeScript and Python**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: Both pass

- [ ] **Step 5: Commit**

```bash
git add frontend/services/chatBackend.ts backend/app/websocket/chat_ws_handler.py backend/app/websocket/chat_turn_executor.py
git commit -m "refactor: rename SSE-era identifiers to WS semantics (StreamEventEnvelope → ChatWsFrame, _parse_sse_event → _parse_stream_event)"
```
