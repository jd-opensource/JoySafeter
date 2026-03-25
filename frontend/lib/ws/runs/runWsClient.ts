'use client'

import { HEARTBEAT, UNRECOVERABLE_CLOSE_CODES, WS_CLOSE_CODE } from '@/lib/ws/constants'
import { getWsRunsUrl } from '@/lib/utils/wsUrl'

import type {
  IncomingRunWsFrame,
  RunConnectionState,
  RunSubscriptionCallbacks,
  RunWsClient,
} from './types'

const MAX_RECONNECT_DELAY_MS = 15000

interface RunSubscriptionState {
  afterSeq: number
  callbacks: RunSubscriptionCallbacks
}

class SharedRunWsClient implements RunWsClient {
  private ws: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private lastPongTime = Date.now()
  private isDisposed = false
  private state: RunConnectionState = { isConnected: false }
  private stateListeners = new Set<(state: RunConnectionState) => void>()
  private subscriptions = new Map<string, RunSubscriptionState>()

  connect(): Promise<void> {
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

    this.connectPromise = getWsRunsUrl().then(
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
              const parsed = JSON.parse(event.data) as IncomingRunWsFrame
              this.handleMessage(parsed)
            } catch {
              // Ignore malformed frames for now; replay can recover.
            }
          }

          ws.onerror = () => {
            this.setConnectionState(false)
            if (this.connectPromise) {
              this.connectPromise = null
              reject(new Error('Run WebSocket connection failed'))
            }
          }

          ws.onclose = (event) => {
            this.stopHeartbeat()
            this.ws = null

            if (this.connectPromise) {
              this.connectPromise = null
              reject(new Error(`Run WebSocket connection failed (${event.code})`))
            }

            if (event.code === WS_CLOSE_CODE.UNAUTHORIZED) {
              this.state = { isConnected: false, authExpired: true }
              this.stateListeners.forEach((listener) => listener(this.state))
              return
            }

            this.setConnectionState(false)
            if (event.code === WS_CLOSE_CODE.NORMAL || this.isDisposed) return
            if (UNRECOVERABLE_CLOSE_CODES.includes(event.code as any)) return
            this.scheduleReconnect()
          }
        }),
    )

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
    }
    this.ws = null
    this.connectPromise = null
    this.setConnectionState(false)
  }

  subscribeConnectionState(listener: (state: RunConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => this.stateListeners.delete(listener)
  }

  getConnectionState(): RunConnectionState {
    return this.state
  }

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

  private handleMessage(frame: IncomingRunWsFrame) {
    if (frame.type === 'pong') {
      this.lastPongTime = Date.now()
      return
    }

    if (frame.type === 'ws_error') {
      this.subscriptions.forEach(({ callbacks }) => callbacks.onError?.(frame.message))
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
      if (frame.seq <= subscription.afterSeq) {
        return
      }
      subscription.afterSeq = frame.seq
      callbacks.onEvent?.(frame)
    }
    if (frame.type === 'replay_done') {
      subscription.afterSeq = Math.max(subscription.afterSeq, frame.last_seq)
      callbacks.onReplayDone?.(frame)
    }
    if (frame.type === 'run_status') callbacks.onStatus?.(frame)
  }

  private setConnectionState(isConnected: boolean) {
    this.state = { isConnected }
    this.stateListeners.forEach((listener) => listener(this.state))
  }

  private startHeartbeat() {
    this.stopHeartbeat()
    this.lastPongTime = Date.now()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return
      if (Date.now() - this.lastPongTime > HEARTBEAT.PONG_TIMEOUT_MS) {
        this.ws.close()
        return
      }
      this.ws.send(JSON.stringify({ type: 'ping' }))
    }, HEARTBEAT.PING_INTERVAL_MS)
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect() {
    if (this.isDisposed || this.reconnectTimer) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY_MS)
    this.reconnectAttempts += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.connect().then(() => {
        const current = Array.from(this.subscriptions.entries())
        current.forEach(([runId, subscription]) => {
          try {
            this.sendFrame({
              type: 'subscribe',
              run_id: runId,
              after_seq: subscription.afterSeq,
            })
          } catch {
            // Ignore; next reconnect or caller recovery can re-subscribe.
          }
        })
      }).catch(() => {})
    }, delay)
  }

  private sendFrame(payload: Record<string, unknown>) {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      throw new Error('Run WebSocket not connected')
    }
    this.ws.send(JSON.stringify(payload))
  }
}

let singleton: SharedRunWsClient | null = null

export function getRunWsClient(): RunWsClient {
  if (!singleton) {
    singleton = new SharedRunWsClient()
  }
  return singleton
}
