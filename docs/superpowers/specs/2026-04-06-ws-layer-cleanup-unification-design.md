# WebSocket Layer Cleanup & Unification Design

**Date:** 2026-04-06
**Branch:** dev-0404
**Scope:** Frontend WS clients, backend dead code, protocol naming, auth unification

## Problem

After migrating streaming chat to WebSocket, the codebase has accumulated:

1. **~200 lines of duplicated code** across `chatWsClient.ts` and `runWsClient.ts` (connect, reconnect, heartbeat, state management, sendFrame, singleton factory).
2. **Inconsistent auth** — notifications WS uses cookie-only auth while chat/runs use short-lived ws-token.
3. **Dead backend endpoints** — `POST /copilot/actions` has no frontend caller.
4. **Legacy protocol tombstones** — `"chat"` frame type accepted only to error, `"resume"`/`"stop"` aliases for `"chat.resume"`/`"chat.stop"`.
5. **Stale naming** — types and functions still reference "SSE" when data flows over WebSocket.
6. **Dead dependency** — `axios` in `package.json` but never imported.
7. **Duplicated constants** — `MAX_RECONNECT_DELAY_MS` defined in two files; `NO_RECONNECT_CLOSE_CODES` vs `UNRECOVERABLE_CLOSE_CODES` overlap.

## Out of Scope

- Internal SSE-to-WS bridge (LangGraph produces SSE strings internally → parsed → forwarded as WS JSON). This is an internal serialization detail with high refactoring risk. Deferred.
- HTTP SSE endpoints (`POST /models/test-output-stream`, `POST /openclaw/chat`). These are independent short-lived streams. Deferred.
- HTTP REST API. CRUD endpoints remain on HTTP by design.

## Design

### Part 1: BaseWsClient Abstract Class

**New file:** `frontend/lib/ws/base/BaseWsClient.ts`

Extract all shared connection lifecycle logic into a generic abstract base class:

```typescript
interface WsClientConfig {
  maxReconnectAttempts: number | null  // chat=20, runs=null (unlimited), notifications=10
                                       // null means no cap — reconnects indefinitely
  maxReconnectDelayMs: number          // 15000
  reconnectStrategy: 'exponential' | 'fixed'  // chat/runs=exponential, notifications=fixed
  fixedReconnectIntervalMs?: number    // only used when strategy='fixed' (notifications=3000)
  pingIntervalMs: number               // 30000 (from HEARTBEAT.PING_INTERVAL_MS)
  pongTimeoutMs: number                // 60000 (from HEARTBEAT.PONG_TIMEOUT_MS)
  name: string                         // "[ChatWS]", "[RunsWS]", "[NotifWS]"
}

abstract class BaseWsClient<TState extends BaseConnectionState> {
  // === Shared fields (currently duplicated) ===
  protected ws: WebSocket | null
  private connectPromise: Promise<void> | null
  private reconnectTimer: ReturnType<typeof setTimeout> | null
  private heartbeatTimer: ReturnType<typeof setInterval> | null
  private reconnectAttempts: number
  private lastPongTime: number
  protected isDisposed: boolean
  private state: TState
  private stateListeners: Set<(state: TState) => void>

  // === Shared methods (move verbatim) ===
  async connect(): Promise<void>        // calls getWsUrl()
  disconnect(): void                     // calls onDispose()
  protected sendFrame(data: object): void // calls createConnectionError()
  private startHeartbeat(): void
  private stopHeartbeat(): void
  private scheduleReconnect(): void      // uses config.reconnectStrategy; calls onReconnected(), onReconnectExhausted()
  protected setConnectionState(isConnected: boolean, extra?: Partial<TState>): void
      // Note: existing callers use setConnectionState(true/false). The base class
      // constructs { ...state, isConnected, ...extra } internally. Subclasses pass
      // extra fields (e.g. authExpired) via the second argument.
  getConnectionState(): TState
  subscribeConnectionState(listener: (state: TState) => void): () => void

  // === Abstract hooks for subclasses ===
  protected abstract getWsUrl(): Promise<string>
  protected abstract handleMessage(data: unknown): void
  protected abstract createInitialState(): TState

  // === Optional hooks (default no-op) ===
  protected onReconnected(): void {}
  protected onReconnectExhausted(): void {}
  protected onDispose(): void {}
  protected createConnectionError(message: string): Error {
    return new Error(message)
  }
}
```

**Base connection state:**

```typescript
interface BaseConnectionState {
  isConnected: boolean
  authExpired?: boolean
}
```

**Subclass responsibilities:**

| Client | `getWsUrl()` | `handleMessage()` | Hooks used |
|---|---|---|---|
| `ChatWsClient` | `getWsChatUrl()` | Route by frame type to pending map | `onDispose` → rejectAllPending, `onReconnectExhausted` → rejectAllPending, `createConnectionError` → ChatWsError |
| `RunWsClient` | `getWsRunsUrl()` | Route to subscription callbacks | `onReconnected` → re-subscribe all active subs. Config: `maxReconnectAttempts=null` (unlimited) |
| `NotificationWsClient` | `getWsNotificationUrl()` (new) | Emit via callback | Config: `maxReconnectAttempts=10`, `reconnectStrategy='fixed'`, `fixedReconnectIntervalMs=3000` |

**Notification hook refactor:**

`use-notification-websocket.ts` changes from inlining all WS logic to holding a `NotificationWsClient` instance via `useRef`. The hook manages only:
- Creating/disposing the client on mount/unmount
- Bridging `handleMessage` callback to React state updates
- Visibility change listener (reconnect on tab focus)

The class-based `NotificationWsClient extends BaseWsClient` replaces the current ~100 lines of inline connection/heartbeat/reconnect code.

**Behavioral changes for NotificationWsClient:**
- **Pong timeout detection added:** The base class checks `lastPongTime` on each heartbeat tick. The current notification hook sends pings but never checks for pongs. Prerequisite: verify that the backend `/ws/notifications` endpoint (via `NotificationManager`) responds to `"ping"` frames with `"pong"`. If the backend does not send pongs, add pong support to `NotificationManager` before migrating.
- **Reconnect strategy preserved:** NotificationWsClient uses `reconnectStrategy: 'fixed'` with `fixedReconnectIntervalMs: 3000` to match existing behavior (not exponential backoff).

**Public API unification — `dispose()` vs `disconnect()`:**

The base class exposes a single public teardown method: **`disconnect()`**. The current `ChatWsClient` exposes `dispose()` while `RunWsClient` exposes `disconnect()`. After migration:
- `SharedChatWsClient` renames `dispose()` → `disconnect()` (inherited from base)
- The `ChatWsClient` interface in `frontend/lib/ws/chat/types.ts` must update `dispose()` → `disconnect()`
- All call sites importing `ChatWsClient` must be updated (search for `.dispose(`)

The `ChatWsClient` interface type in `chat/types.ts` continues to exist as the consumer-facing contract. `SharedChatWsClient extends BaseWsClient implements ChatWsClient` — the interface is updated to match the base class public API.

### Part 2: Unified Authentication

**Current state:**
- Chat/Runs: `GET /api/v1/auth/ws-token` → 60-second JWT → `?token=` query param
- Notifications: Cookie-only (relies on `authenticate_websocket()` trying cookie first)

**Change:**
- Create `getWsNotificationUrl()` in `wsUrl.ts` using the same `getWsTokenUrl()` pattern
- `NotificationWsClient.getWsUrl()` calls this new function
- Backend `authenticate_websocket()` unchanged — it already supports both paths
- Result: all three WS connections use identical auth flow

**Why:** Security (short-lived token > long-lived cookie for WS), consistency, and cross-origin readiness.

### Part 3: Dead Code Removal

| Item | Location | Action |
|---|---|---|
| `POST /copilot/actions` endpoint | `backend/app/api/v1/graphs.py:649` | Delete the route handler only. `CopilotResponse` model is still used by `CopilotService` in the service layer — do NOT delete it. |
| `axios` dependency | `frontend/package.json:64` | Run `npm uninstall axios` or `bun remove axios`. |
| `"chat"` in `ALLOWED_CLIENT_FRAME_TYPES` | `backend/app/websocket/chat_protocol.py:12` | Remove `"chat"` from the set. Remove the explicit rejection block at lines 92-96. Unknown `"chat"` frames will now get the standard "unknown frame type" error. |
| `"resume"` / `"stop"` aliases | `chat_protocol.py:16-17`, `chat_ws_handler.py:126-130` | Remove from `ALLOWED_CLIENT_FRAME_TYPES`. Update handler dispatch to only accept `"chat.resume"` / `"chat.stop"`. Verify no frontend code sends the old aliases (confirmed: frontend only uses `chat.stop`/`chat.resume`). |
| `RESERVED_METADATA_KEYS` check | `chat_protocol.py` | Simplify or remove if the `"chat"` path is gone — the reserved keys were only checked to give a better error when migrating from the old format. |

### Part 4: Naming Corrections

Rename SSE-era identifiers to reflect the actual WebSocket transport:

| Old Name | New Name | File(s) |
|---|---|---|
| `StreamEventEnvelope` | `ChatWsFrame` | `frontend/services/chatBackend.ts` |
| `_parse_sse_event()` | `_parse_stream_event()` | `backend/app/websocket/chat_ws_handler.py` (definition), `backend/app/websocket/chat_turn_executor.py` (call sites via `handler._parse_sse_event`) |
| `_send_event_from_sse()` | `_send_stream_event()` | `backend/app/websocket/chat_ws_handler.py` (definition), `backend/app/websocket/chat_turn_executor.py` (call sites at lines ~258, 289, 614, 628 via `handler._send_event_from_sse`) |
| Comments referencing "SSE" in WS context | Update to "stream event" or "WS frame" | Various |

**Note:** The internal SSE bridge (LangGraph → SSE string → parse → WS JSON) is out of scope. These renames only affect the WS-facing surface, not the internal bridge code.

### Part 5: Constants Consolidation

**Target file:** `frontend/lib/ws/constants.ts` (already exists)

Add to existing constants:

```typescript
export const RECONNECT = {
  MAX_DELAY_MS: 15_000,           // was duplicated in chatWsClient.ts:31 and runWsClient.ts:13
  DEFAULT_MAX_ATTEMPTS: 20,        // was private static in chatWsClient only
  NOTIFICATION_MAX_ATTEMPTS: 10,   // was in use-notification-websocket.ts
} as const
```

Remove redundant constants:
- Delete `NO_RECONNECT_CLOSE_CODES` — keep only `UNRECOVERABLE_CLOSE_CODES` (which includes `WS_CLOSE_CODE.NORMAL`). The base class handles normal close internally.
- Move the `MAX_RECONNECT_DELAY_MS` module-scope definitions from both client files into the shared constants.

## Execution Order

Each part is an independent, testable change. Recommended order:

1. **Part 5a: Constants consolidation** — Add `RECONNECT` constants to `constants.ts`. Do NOT delete `NO_RECONNECT_CLOSE_CODES` yet (notification hook still imports it).
2. **Part 1: BaseWsClient** — the core change, biggest value. Migrate chat → runs → notifications in sequence. After notification hook migrates to `NotificationWsClient`, it no longer imports `NO_RECONNECT_CLOSE_CODES`.
3. **Part 5b: Constants cleanup** — Now safe to delete `NO_RECONNECT_CLOSE_CODES` and remove duplicated module-scope constants from the old client files.
4. **Part 2: Auth unification** — small change on top of Part 1
5. **Part 3: Dead code removal** — independent of Parts 1-2, can be done in parallel with any step
6. **Part 4: Naming** — cosmetic, lowest priority, independent

Parts 3 and 4 have no dependency on Parts 1-2 and could be done first or in parallel.

## Risk Assessment

| Part | Risk | Mitigation |
|---|---|---|
| BaseWsClient | Medium — touches all real-time connections | Implement and test one client at a time; run existing WS integration tests after each migration |
| Auth unification | Low — backend already supports token path | Test notification WS with token before removing cookie fallback |
| Dead code removal | Low — confirmed no callers | Grep verification before each deletion |
| Naming | Low — find-and-replace with type checking | TypeScript compiler catches missed renames |
| Constants | Very low — value extraction only | Trivial |

## Testing Strategy

- **Unit:** BaseWsClient with mock WebSocket (test connect, reconnect backoff, heartbeat timeout, auth expiry)
- **Integration:** Each migrated client sends/receives frames correctly, reconnects after server restart, handles auth expiry
- **Manual QA:** Chat streaming, run event replay, notification delivery, tab-switch reconnect
