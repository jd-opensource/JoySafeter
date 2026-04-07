'use client'

import { getWsNotificationUrl } from '@/lib/utils/wsUrl'

import { BaseWsClient } from '../base'
import type { BaseConnectionState } from '../base'

export interface NotificationMessage {
  type: string
  data?: Record<string, unknown>
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
