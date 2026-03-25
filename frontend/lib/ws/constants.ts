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
