import { afterEach, describe, expect, it, vi } from 'vitest'

// Mock next-runtime-env so getWsBaseUrl falls through to the ws://localhost:8000 default
vi.mock('next-runtime-env', () => ({ env: vi.fn(() => undefined) }))

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

class MockWs {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3

  readyState = MockWs.OPEN
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: (() => void) | null = null

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.readyState = MockWs.CLOSED
  }

  /** Simulate the server delivering a frame to this socket */
  receive(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

let mockWsInstance: MockWs

vi.stubGlobal(
  'WebSocket',
  class extends MockWs {
    constructor(_url: string) {
      super()
      // eslint-disable-next-line @typescript-eslint/no-this-alias
      mockWsInstance = this
      // Simulate async open so callers can attach handlers first
      Promise.resolve().then(() => this.onopen?.())
    }
  },
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Flush the microtask queue multiple times to drain chained promises */
async function flushPromises(rounds = 5) {
  for (let i = 0; i < rounds; i++) {
    await new Promise<void>((r) => setTimeout(r, 0))
  }
}

// The service exports a singleton, so we import it once at module scope.
// vi.resetModules() in afterEach ensures a clean instance between tests.
import type { workspaceChatWsService as WorkspaceChatWsServiceType } from '../workspaceChatWsService'

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('workspaceChatWsService', () => {
  afterEach(() => {
    vi.resetModules()
  })

  /** Load a fresh singleton (after vi.resetModules) and wait for the WS to open */
  async function makeConnectedService(): Promise<typeof WorkspaceChatWsServiceType> {
    // Dynamic import picks up a fresh module evaluation after resetModules
    const mod = await import('../workspaceChatWsService')
    const svc = mod.workspaceChatWsService

    // Kick off the connection; MockWs fires onopen in the next microtask tick
    const connectP = svc.ensureConnected()
    await flushPromises()
    await connectP
    return svc
  }

  // -------------------------------------------------------------------------
  // 1. sendChat resolves with { requestId, threadId } on 'done'
  // -------------------------------------------------------------------------
  it('sendChat resolves with requestId and threadId when done frame is received', async () => {
    const svc = await makeConnectedService()

    const sendP = svc.sendChat({ message: 'hello' })
    await flushPromises(2)

    expect(mockWsInstance.sent.length).toBeGreaterThanOrEqual(1)
    const chatFrame = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])
    const { request_id } = chatFrame

    // Server delivers thread info then signals completion
    mockWsInstance.receive({ type: 'content', request_id, thread_id: 'thread-abc', data: { delta: 'hi' } })
    mockWsInstance.receive({ type: 'done', request_id, thread_id: 'thread-abc' })

    const result = await sendP

    expect(result).toMatchObject({ requestId: request_id, threadId: 'thread-abc' })
  })

  // -------------------------------------------------------------------------
  // 2. sendChat rejects when error frame carries a non-stop message
  // -------------------------------------------------------------------------
  it('sendChat rejects with error message when error frame is received', async () => {
    const svc = await makeConnectedService()

    const sendP = svc.sendChat({ message: 'hello' })
    await flushPromises(2)

    const { request_id } = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])

    mockWsInstance.receive({
      type: 'error',
      request_id,
      data: { message: 'Something went terribly wrong' },
    })

    await expect(sendP).rejects.toThrow('Something went terribly wrong')
  })

  // -------------------------------------------------------------------------
  // 3. sendChat resolves (does NOT reject) when error frame says "Stream stopped"
  // -------------------------------------------------------------------------
  it('sendChat resolves when error frame says "Stream stopped"', async () => {
    const svc = await makeConnectedService()

    const sendP = svc.sendChat({ message: 'hello', threadId: 'thread-xyz' })
    await flushPromises(2)

    const { request_id } = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])

    mockWsInstance.receive({
      type: 'error',
      request_id,
      thread_id: 'thread-xyz',
      data: { message: 'Stream stopped' },
    })

    const result = await sendP

    expect(result).toMatchObject({ requestId: request_id })
  })

  // -------------------------------------------------------------------------
  // 4. Pending promises are rejected with "WebSocket disconnected" on close
  // -------------------------------------------------------------------------
  it('pending sendChat promises are rejected with "WebSocket disconnected" when socket closes', async () => {
    const svc = await makeConnectedService()

    const sendP = svc.sendChat({ message: 'hello' })
    await flushPromises(2)

    // Simulate the socket closing before any response arrives
    mockWsInstance.onclose?.({ code: 1006 })

    await expect(sendP).rejects.toThrow('WebSocket disconnected')
  })

  // -------------------------------------------------------------------------
  // 5. stopByThreadId sends a stop frame with the correct request_id
  // -------------------------------------------------------------------------
  it('stopByThreadId sends a stop frame with the correct request_id', async () => {
    const svc = await makeConnectedService()

    const sendP = svc.sendChat({ message: 'hello', threadId: 'thread-stop' })
    await flushPromises(2)

    const { request_id } = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])

    // Server notifies the client of the thread_id so threadToRequest is populated
    mockWsInstance.receive({ type: 'content', request_id, thread_id: 'thread-stop', data: { delta: '' } })

    // Client requests stop
    svc.stopByThreadId('thread-stop')

    const stopFrame = JSON.parse(mockWsInstance.sent[mockWsInstance.sent.length - 1])

    expect(stopFrame).toMatchObject({ type: 'stop', request_id })

    // Resolve the dangling promise cleanly
    mockWsInstance.receive({ type: 'done', request_id, thread_id: 'thread-stop' })
    await sendP
  })
})
