import { act, cleanup, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { NotificationMessage } from './use-notification-websocket'

const { mockClients, MockNotificationWsClient } = vi.hoisted(() => {
  const clients: MockNotificationWsClientImpl[] = []

  class MockNotificationWsClientImpl {
    handler: ((notification: NotificationMessage) => void) | null = null
    listeners = new Set<(state: { isConnected: boolean }) => void>()
    connect = vi.fn(async () => {})
    disconnect = vi.fn()

    constructor() {
      clients.push(this)
    }

    setNotificationHandler(handler: ((notification: NotificationMessage) => void) | null) {
      this.handler = handler
    }

    subscribeConnectionState(listener: (state: { isConnected: boolean }) => void) {
      this.listeners.add(listener)
      listener({ isConnected: false })
      return () => {
        this.listeners.delete(listener)
      }
    }

    getConnectionState() {
      return { isConnected: false }
    }

    emit(notification: NotificationMessage) {
      this.handler?.(notification)
    }
  }

  return { mockClients: clients, MockNotificationWsClient: MockNotificationWsClientImpl }
})

vi.mock('@/lib/ws/notifications/NotificationWsClient', () => ({
  NotificationWsClient: MockNotificationWsClient,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

import { useNotificationWebSocket } from './use-notification-websocket'

describe('useNotificationWebSocket lifecycle', () => {
  beforeEach(() => {
    mockClients.length = 0
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('clears the previous user notification when the user disconnects', async () => {
    const { result, rerender } = renderHook(
      ({ userId }: { userId: string | null }) => useNotificationWebSocket({ userId }),
      {
        initialProps: { userId: 'user-a' },
      },
    )

    expect(mockClients).toHaveLength(1)

    act(() => {
      mockClients[0].emit({
        type: 'task.updated',
        data: { id: 'task-a' },
      })
    })

    expect(result.current.lastNotification).toMatchObject({
      type: 'task.updated',
      data: { id: 'task-a' },
    })

    await act(async () => {
      rerender({ userId: null })
      await Promise.resolve()
    })

    expect(mockClients[0].disconnect).toHaveBeenCalledTimes(1)
    expect(result.current.lastNotification).toBeNull()

    act(() => {
      mockClients[0].emit({
        type: 'task.updated',
        data: { id: 'task-after-disconnect' },
      })
    })

    expect(result.current.lastNotification).toBeNull()
  })

  it('does not connect automatically when autoReconnect is disabled', async () => {
    const { result } = renderHook(() =>
      useNotificationWebSocket({
        userId: 'user-a',
        autoReconnect: false,
      }),
    )

    expect(mockClients).toHaveLength(0)

    await act(async () => {
      result.current.reconnect()
      await Promise.resolve()
    })

    expect(mockClients).toHaveLength(1)
    expect(mockClients[0].connect).toHaveBeenCalledTimes(1)
  })
})
