# WebSocket Robustness & Consistency Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all WebSocket error handling inconsistencies across 3 frontend WS clients and 1 backend handler, unifying close-code handling, heartbeat detection, reconnection caps, and type safety.

**Architecture:** Extract shared WS constants (close codes, heartbeat config) into a single source of truth. Add pong-timeout detection to Chat client. Unify close-code handling across all 3 frontend hooks. Fix type declarations. Add minimal logging for parse failures.

**Tech Stack:** TypeScript, React hooks, FastAPI/Python (backend — OpenClaw handler only)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `frontend/lib/ws/constants.ts` | Shared WS constants: close codes, heartbeat config, reconnect config |
| **Modify** | `frontend/lib/ws/chat/types.ts` | Add `authExpired` to `ConnectionState` |
| **Modify** | `frontend/lib/ws/chat/chatWsClient.ts` | Pong timeout detection, max reconnect limit, unrecoverable close-code handling, import shared constants |
| **Modify** | `frontend/hooks/use-copilot-websocket.ts` | Unrecoverable close-code handling (4001/4003/4004), import shared constants |
| **Modify** | `frontend/hooks/use-notification-websocket.ts` | Add `console.error` to `onerror`, add 4004 to no-reconnect codes, import shared constants |
| **Modify** | `backend/app/websocket/openclaw_handler.py` | Add application-level ping/pong heartbeat |

---

### Task 1: Create shared WS constants

**Files:**
- Create: `frontend/lib/ws/constants.ts`

- [ ] **Step 1: Create the constants file**

```ts
/**
 * Shared WebSocket constants used by all WS clients/hooks.
 * Single source of truth for close codes, heartbeat, and reconnect config.
 */

/** Backend-defined custom close codes (see backend/app/websocket/auth.py) */
export const WS_CLOSE_CODE = {
  NORMAL: 1000,
  POLICY_VIOLATION: 1008,
  INTERNAL_ERROR: 1011,
  UNAUTHORIZED: 4001,
  FORBIDDEN: 4003,
  NOT_FOUND: 4004,
} as const

/**
 * Close codes that indicate unrecoverable errors — reconnecting is pointless.
 * 4001: auth expired/invalid
 * 4003: forbidden (user mismatch)
 * 4004: resource not found
 */
export const UNRECOVERABLE_CLOSE_CODES = [
  WS_CLOSE_CODE.UNAUTHORIZED,
  WS_CLOSE_CODE.FORBIDDEN,
  WS_CLOSE_CODE.NOT_FOUND,
] as const

/** Close codes where reconnection should be skipped (normal + unrecoverable) */
export const NO_RECONNECT_CLOSE_CODES = [
  WS_CLOSE_CODE.NORMAL,
  ...UNRECOVERABLE_CLOSE_CODES,
] as const

/** Heartbeat configuration */
export const HEARTBEAT = {
  /** Interval between ping sends (ms) */
  PING_INTERVAL_MS: 30_000,
  /** Max time to wait for pong before considering connection dead (ms) */
  PONG_TIMEOUT_MS: 60_000,
} as const
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/ws/constants.ts
git commit -m "feat(ws): add shared WebSocket constants for close codes and heartbeat config"
```

---

### Task 2: Fix `ConnectionState` type and `authExpired` handling in Chat WS

**Files:**
- Modify: `frontend/lib/ws/chat/types.ts:43-45`
- Modify: `frontend/lib/ws/chat/chatWsClient.ts:86-103` (onclose handler)

- [ ] **Step 1: Add `authExpired` to `ConnectionState` in `types.ts`**

In `frontend/lib/ws/chat/types.ts`, change:

```ts
export interface ConnectionState {
  isConnected: boolean
}
```

to:

```ts
export interface ConnectionState {
  isConnected: boolean
  authExpired?: boolean
}
```

- [ ] **Step 2: Set `authExpired` in `chatWsClient.ts` onclose handler**

In `frontend/lib/ws/chat/chatWsClient.ts`, in the `ws.onclose` handler, replace the close-code logic block (lines ~96-103):

```ts
// OLD:
if (event.code === 1000 || this.isDisposed) {
  return
}

this.rejectAllPending(
  new ChatWsError('WS_CONNECTION_LOST', event.code === 4001 ? 'Authentication expired' : 'WebSocket disconnected'),
)
this.scheduleReconnect()
```

with (importing from constants):

```ts
import { NO_RECONNECT_CLOSE_CODES, WS_CLOSE_CODE, UNRECOVERABLE_CLOSE_CODES } from '../constants'

// ... inside onclose:

if (event.code === WS_CLOSE_CODE.UNAUTHORIZED) {
  this.state = { isConnected: false, authExpired: true }
  this.stateListeners.forEach((l) => l(this.state))
  this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Authentication expired'))
  return
}

if (event.code === WS_CLOSE_CODE.NORMAL || this.isDisposed) {
  return
}

this.rejectAllPending(
  new ChatWsError('WS_CONNECTION_LOST', 'WebSocket disconnected'),
)

if (UNRECOVERABLE_CLOSE_CODES.includes(event.code as any)) {
  return  // Don't reconnect for 4003, 4004
}

this.scheduleReconnect()
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/ws/chat/types.ts frontend/lib/ws/chat/chatWsClient.ts
git commit -m "fix(ws/chat): add authExpired to ConnectionState, stop reconnect on unrecoverable close codes"
```

---

### Task 3: Add pong timeout detection and max reconnect limit to Chat WS

**Files:**
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`

- [ ] **Step 1: Add `lastPongTime` tracking and max reconnect**

Add class fields:

```ts
private lastPongTime = Date.now()
private static readonly MAX_RECONNECT_ATTEMPTS = 20
```

- [ ] **Step 2: Update `handleInboundMessage` to track pong time**

Change:

```ts
if (!type || type === 'pong') return
```

to:

```ts
if (!type) return
if (type === 'pong') {
  this.lastPongTime = Date.now()
  return
}
```

- [ ] **Step 3: Update `startHeartbeat` to check pong timeout**

Replace the `startHeartbeat` method:

```ts
private startHeartbeat() {
  this.stopHeartbeat()
  this.lastPongTime = Date.now()
  this.heartbeatTimer = setInterval(() => {
    if (this.ws?.readyState !== WebSocket.OPEN) return

    if (Date.now() - this.lastPongTime > HEARTBEAT.PONG_TIMEOUT_MS) {
      console.warn('[ChatWS] Heartbeat timeout — no pong in 60s, reconnecting')
      // Force-close the dead socket; onclose will trigger reconnect
      this.ws.close()
      return
    }

    this.ws.send(JSON.stringify({ type: 'ping' }))
  }, HEARTBEAT.PING_INTERVAL_MS)
}
```

- [ ] **Step 4: Add max reconnect cap to `scheduleReconnect`**

Replace:

```ts
private scheduleReconnect() {
  if (this.isDisposed || this.reconnectTimer) return
  const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY_MS)
  this.reconnectAttempts += 1
  this.reconnectTimer = setTimeout(() => {
    this.reconnectTimer = null
    void this.connect().catch(() => {})
  }, delay)
}
```

with:

```ts
private scheduleReconnect() {
  if (this.isDisposed || this.reconnectTimer) return

  if (this.reconnectAttempts >= SharedChatWsClient.MAX_RECONNECT_ATTEMPTS) {
    console.error('[ChatWS] Max reconnect attempts reached')
    this.rejectAllPending(new ChatWsError('WS_CONNECTION_LOST', 'Connection lost. Please refresh the page.'))
    return
  }

  const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY_MS)
  this.reconnectAttempts += 1
  this.reconnectTimer = setTimeout(() => {
    this.reconnectTimer = null
    void this.connect().catch(() => {})
  }, delay)
}
```

- [ ] **Step 5: Remove the module-level `HEARTBEAT_INTERVAL_MS` constant**

Replace:

```ts
const HEARTBEAT_INTERVAL_MS = 30000
```

The file now imports `HEARTBEAT` from `../constants` instead.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/ws/chat/chatWsClient.ts
git commit -m "fix(ws/chat): add pong timeout detection and max reconnect limit"
```

---

### Task 4: Unify Copilot WS close-code handling

**Files:**
- Modify: `frontend/hooks/use-copilot-websocket.ts`

- [ ] **Step 1: Import shared constants and replace inline `noReconnectCodes`**

Add import at top:

```ts
import { NO_RECONNECT_CLOSE_CODES, WS_CLOSE_CODE } from '@/lib/ws/constants'
```

- [ ] **Step 2: Replace `noReconnectCodes` in `onclose`**

Change:

```ts
const noReconnectCodes = [1000]
```

to:

```ts
const noReconnectCodes: readonly number[] = NO_RECONNECT_CLOSE_CODES
```

- [ ] **Step 3: Add auth-expired redirect for 4001**

Add at the beginning of `ws.onclose` handler, before the reconnect logic:

```ts
if (event.code === WS_CLOSE_CODE.UNAUTHORIZED) {
  cleanup()
  window.location.assign('/signin')
  return
}
```

- [ ] **Step 4: Remove the duplicated `getWsBaseUrl` function**

Replace the local `getWsBaseUrl()` function (lines 61-70) with an import from the shared module:

```ts
import { getWsBaseUrl } from '@/lib/utils/wsUrl'
```

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/use-copilot-websocket.ts
git commit -m "fix(ws/copilot): handle unrecoverable close codes, redirect on auth expiry"
```

---

### Task 5: Fix Notification WS — error logging, close codes, remove dup

**Files:**
- Modify: `frontend/hooks/use-notification-websocket.ts`

- [ ] **Step 1: Import shared constants and replace `getWsBaseUrl`**

Add imports:

```ts
import { NO_RECONNECT_CLOSE_CODES } from '@/lib/ws/constants'
import { getWsBaseUrl } from '@/lib/utils/wsUrl'
```

Remove the local `getWsBaseUrl()` function (lines 27-36).

- [ ] **Step 2: Replace `noReconnectCodes` in `onclose`**

Change:

```ts
const noReconnectCodes = [1000, 4001, 4003]
```

to:

```ts
const noReconnectCodes: readonly number[] = NO_RECONNECT_CLOSE_CODES
```

This now also includes 4004.

- [ ] **Step 3: Add console.error to `onerror`**

Change:

```ts
ws.onerror = () => {}
```

to:

```ts
ws.onerror = (event) => {
  console.error('[NotificationWS] Connection error:', event)
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-notification-websocket.ts
git commit -m "fix(ws/notification): add error logging, unify close codes, use shared getWsBaseUrl"
```

---

### Task 6: Add heartbeat to OpenClaw Bridge (backend)

**Files:**
- Modify: `backend/app/websocket/openclaw_handler.py`

- [ ] **Step 1: Add periodic ping task to the bridge**

Add a third concurrent task that sends a ping to the gateway every 30 seconds. Replace the two-task wait with a three-task wait:

```python
async def handle_bridge(self, ws: WebSocket, user_id: str) -> None:
    # ... (existing code up to websockets.connect)

    async with websockets.connect(...) as gw_ws:
        client_to_gw = asyncio.create_task(self._forward_client_to_gateway(ws, gw_ws, user_id))
        gw_to_client = asyncio.create_task(self._forward_gateway_to_client(ws, gw_ws, user_id))
        heartbeat = asyncio.create_task(self._heartbeat(gw_ws, user_id))

        done, pending = await asyncio.wait(
            [client_to_gw, gw_to_client, heartbeat],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
```

Add the heartbeat method:

```python
async def _heartbeat(self, gw_ws, user_id: str) -> None:
    """Send periodic pings to detect dead upstream connections."""
    try:
        while True:
            await asyncio.sleep(30)
            await gw_ws.ping()
    except Exception as e:
        logger.debug(f"Heartbeat ended for user={user_id}: {e}")
```

The `websockets` library handles pong timeout automatically — `gw_ws.ping()` raises `ConnectionClosed` if the peer doesn't respond within the library's default timeout (20s).

- [ ] **Step 2: Commit**

```bash
git add backend/app/websocket/openclaw_handler.py
git commit -m "fix(ws/openclaw): add heartbeat ping to detect dead upstream connections"
```

---

### Task 7: Add JSON parse failure counter to Chat WS client

**Files:**
- Modify: `frontend/lib/ws/chat/chatWsClient.ts`

- [ ] **Step 1: Add parse failure counter and threshold**

Add class field:

```ts
private consecutiveParseFailures = 0
private static readonly MAX_PARSE_FAILURES = 10
```

- [ ] **Step 2: Update `onmessage` handler to count failures**

Replace:

```ts
ws.onmessage = (event) => {
  try {
    this.handleInboundMessage(JSON.parse(event.data) as IncomingChatWsEvent)
  } catch {
    // Ignore malformed frames from the server.
  }
}
```

with:

```ts
ws.onmessage = (event) => {
  try {
    const parsed = JSON.parse(event.data) as IncomingChatWsEvent
    this.consecutiveParseFailures = 0
    this.handleInboundMessage(parsed)
  } catch {
    this.consecutiveParseFailures++
    console.warn(`[ChatWS] Malformed frame (${this.consecutiveParseFailures} consecutive)`)
    if (this.consecutiveParseFailures >= SharedChatWsClient.MAX_PARSE_FAILURES) {
      console.error('[ChatWS] Too many consecutive parse failures, reconnecting')
      this.consecutiveParseFailures = 0
      this.ws?.close()
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/ws/chat/chatWsClient.ts
git commit -m "fix(ws/chat): add parse failure counter, reconnect after 10 consecutive bad frames"
```

---

### Task 8: Verify and smoke test

- [ ] **Step 1: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 2: Run existing tests if any**

```bash
cd frontend && npm test -- --passWithNoTests 2>&1 | head -50
```

- [ ] **Step 3: Final commit if any lint/type fixes needed**
