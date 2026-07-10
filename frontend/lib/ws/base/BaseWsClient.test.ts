import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WS_CLOSE_CODE } from '../constants'
import { BaseWsClient, type BaseConnectionState } from './BaseWsClient'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function flushMicrotasks() {
  await Promise.resolve()
  await Promise.resolve()
}

async function promiseState<T>(promise: Promise<T>) {
  return Promise.race([
    promise.then(
      () => 'resolved' as const,
      () => 'rejected' as const,
    ),
    new Promise<'pending'>((resolve) => setTimeout(() => resolve('pending'), 0)),
  ])
}

class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  send = vi.fn()
  close = vi.fn((code = WS_CLOSE_CODE.NORMAL) => {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({ code })
  })

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }
}

class TestWsClient extends BaseWsClient<BaseConnectionState> {
  readonly messages: unknown[] = []

  constructor(private readonly urls: Array<Promise<string>>) {
    super({ name: '[TestWS]' })
  }

  protected createInitialState(): BaseConnectionState {
    return { isConnected: false }
  }

  protected getWsUrl(): Promise<string> {
    const next = this.urls.shift()
    if (!next) throw new Error('missing test url')
    return next
  }

  protected handleMessage(data: unknown): void {
    this.messages.push(data)
  }
}

describe('BaseWsClient lifecycle', () => {
  let originalWebSocket: typeof WebSocket | undefined

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    FakeWebSocket.instances = []
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
  })

  afterEach(() => {
    if (originalWebSocket) {
      globalThis.WebSocket = originalWebSocket
    } else {
      delete (globalThis as { WebSocket?: typeof WebSocket }).WebSocket
    }
    vi.restoreAllMocks()
  })

  it('cancels a pending URL lookup without creating a socket after disconnect', async () => {
    const url = deferred<string>()
    const client = new TestWsClient([url.promise])

    const connectPromise = client.connect()
    client.disconnect()

    await expect(promiseState(connectPromise)).resolves.toBe('rejected')

    url.resolve('ws://example.test/late')
    await flushMicrotasks()

    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(client.getConnectionState().isConnected).toBe(false)
  })

  it('rejects an in-flight connection attempt when disconnect closes a connecting socket', async () => {
    const client = new TestWsClient([Promise.resolve('ws://example.test/live')])

    const connectPromise = client.connect()
    await flushMicrotasks()

    expect(FakeWebSocket.instances).toHaveLength(1)
    const socket = FakeWebSocket.instances[0]

    client.disconnect()

    expect(socket.close).toHaveBeenCalledTimes(1)
    await expect(promiseState(connectPromise)).resolves.toBe('rejected')
    expect(client.getConnectionState().isConnected).toBe(false)
  })

  it('clears stale auth-expired state after a successful reconnect', async () => {
    const client = new TestWsClient([
      Promise.resolve('ws://example.test/expired'),
      Promise.resolve('ws://example.test/reconnected'),
    ])

    const firstConnect = client.connect()
    await flushMicrotasks()
    FakeWebSocket.instances[0].open()
    await firstConnect

    FakeWebSocket.instances[0].close(WS_CLOSE_CODE.UNAUTHORIZED)

    expect(client.getConnectionState()).toEqual({
      isConnected: false,
      authExpired: true,
    })

    const secondConnect = client.connect()
    await flushMicrotasks()
    FakeWebSocket.instances[1].open()
    await secondConnect

    expect(client.getConnectionState()).toEqual({
      isConnected: true,
      authExpired: false,
    })
  })
})
