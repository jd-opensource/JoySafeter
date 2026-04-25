'use client'

import { getWsExecutionsUrl } from '@/lib/utils/wsUrl'

import { BaseWsClient } from '../base'
import type {
  ExecutionConnectionState,
  ExecutionSubscriptionCallbacks,
  IncomingExecutionWsFrame,
} from './types'

interface ExecutionSubscriptionState {
  afterSeq: number
  callbacks: ExecutionSubscriptionCallbacks
}

class SharedExecutionWsClient extends BaseWsClient<ExecutionConnectionState> {
  private subscriptions = new Map<string, ExecutionSubscriptionState>()

  constructor() {
    super({
      maxReconnectAttempts: null,
      name: '[ExecWS]',
    })
  }

  protected createInitialState(): ExecutionConnectionState {
    return { isConnected: false }
  }

  protected async getWsUrl(): Promise<string> {
    return getWsExecutionsUrl()
  }

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

  protected override onReconnected(): void {
    for (const [execId, subscription] of this.subscriptions) {
      try {
        this.sendFrame({
          type: 'subscribe',
          execution_id: execId,
          after_seq: subscription.afterSeq,
        })
      } catch {
        // Next reconnect will retry.
      }
    }
  }

  async subscribe(
    executionId: string,
    afterSeq: number,
    callbacks: ExecutionSubscriptionCallbacks,
  ): Promise<void> {
    await this.connect()
    const existing = this.subscriptions.get(executionId)
    const normalizedAfterSeq = existing ? Math.max(existing.afterSeq, afterSeq) : afterSeq
    this.subscriptions.set(executionId, {
      afterSeq: normalizedAfterSeq,
      callbacks,
    })
    this.sendFrame({
      type: 'subscribe',
      execution_id: executionId,
      after_seq: normalizedAfterSeq,
    })
  }

  unsubscribe(executionId: string): void {
    this.subscriptions.delete(executionId)
    try {
      this.sendFrame({ type: 'unsubscribe', execution_id: executionId })
    } catch {
      // Ignore connection errors on unsubscribe.
    }
  }
}

let singleton: SharedExecutionWsClient | null = null

export function getExecutionWsClient(): SharedExecutionWsClient {
  if (!singleton) {
    singleton = new SharedExecutionWsClient()
  }
  return singleton
}
