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

  protected onReconnected(): void {}
  protected onReconnectExhausted(): void {}
  protected onDispose(): void {}
  protected onAuthExpired(): void {}
  protected onUnexpectedClose(): void {}
  protected onParseError(): void {}
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
