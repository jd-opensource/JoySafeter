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
