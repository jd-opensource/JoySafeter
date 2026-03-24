import type { Dispatch } from 'react'
import { renderHook, act, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

// Mock next-runtime-env so getWsBaseUrl falls through to the ws://localhost:8000 default
vi.mock('next-runtime-env', () => ({ env: vi.fn(() => undefined) }))

// Mock toast so it does not throw during error paths
vi.mock('@/lib/utils/toast', () => ({ toastError: vi.fn() }))

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

  /** Simulate the server delivering a frame */
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
      mockWsInstance = this
      // Fire onopen asynchronously so the hook can attach its handlers first
      Promise.resolve().then(() => this.onopen?.())
    }
  },
)

// ---------------------------------------------------------------------------
// Import the hook
// ---------------------------------------------------------------------------
import { useChatWebSocket } from '../useChatWebSocket'
import type { ChatAction } from '../../useChatReducer'

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/** Render the hook and wait until the WebSocket reports as connected */
async function renderConnectedHook() {
  const dispatch = vi.fn() as unknown as Dispatch<ChatAction> & ReturnType<typeof vi.fn>
  const utils = renderHook(() => useChatWebSocket(dispatch))

  // Wait for the hook's connect() useEffect + MockWs onopen microtask to settle
  await waitFor(() => {
    expect(utils.result.current.isConnected).toBe(true)
  })

  return { dispatch, utils, ws: mockWsInstance }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useChatWebSocket', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  // -------------------------------------------------------------------------
  // 1. 'content' event dispatches STREAM_CONTENT with correct delta
  // -------------------------------------------------------------------------
  it('content event dispatches STREAM_CONTENT action with the correct delta', async () => {
    const { dispatch, utils, ws } = await renderConnectedHook()

    // sendMessage returns only after a done frame, so we fire it concurrently
    let requestId!: string
    let sendP!: Promise<{ requestId: string }>

    await act(async () => {
      sendP = utils.result.current.sendMessage({ message: 'hi' })
      // Let the synchronous ws.send() inside sendMessage run
      await Promise.resolve()
    })

    requestId = JSON.parse(ws.sent[ws.sent.length - 1]).request_id
    expect(requestId).toBeTruthy()

    // Find the aiMsgId dispatched via APPEND_MESSAGE
    const appendCall = dispatch.mock.calls.find(([a]) => a.type === 'APPEND_MESSAGE')
    expect(appendCall).toBeDefined()
    const aiMsgId = (appendCall![0] as Extract<ChatAction, { type: 'APPEND_MESSAGE' }>).message.id

    // Deliver a content frame
    await act(async () => {
      ws.receive({ type: 'content', request_id: requestId, data: { delta: 'Hello world' } })
    })

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'STREAM_CONTENT',
        delta: 'Hello world',
        messageId: aiMsgId,
      }),
    )

    // Clean up the dangling sendP
    await act(async () => {
      ws.receive({ type: 'done', request_id: requestId })
    })
    await sendP
  })

  // -------------------------------------------------------------------------
  // 2. 'done' event dispatches STREAM_DONE and cleans up activeRequestsRef
  // -------------------------------------------------------------------------
  it('done event dispatches STREAM_DONE and removes the request from activeRequestsRef', async () => {
    const { dispatch, utils, ws } = await renderConnectedHook()

    let requestId!: string
    let sendP!: Promise<{ requestId: string }>

    await act(async () => {
      sendP = utils.result.current.sendMessage({ message: 'hi' })
      await Promise.resolve()
    })

    requestId = JSON.parse(ws.sent[ws.sent.length - 1]).request_id

    const appendCall = dispatch.mock.calls.find(([a]) => a.type === 'APPEND_MESSAGE')
    const aiMsgId = (appendCall![0] as Extract<ChatAction, { type: 'APPEND_MESSAGE' }>).message.id

    dispatch.mockClear()

    await act(async () => {
      ws.receive({ type: 'done', request_id: requestId, thread_id: 'thread-1' })
    })
    await sendP

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_DONE', messageId: aiMsgId }),
    )

    // Verify cleanup: a subsequent content frame for the same requestId is ignored
    dispatch.mockClear()

    await act(async () => {
      ws.receive({ type: 'content', request_id: requestId, data: { delta: 'late delta' } })
    })

    expect(dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_CONTENT' }),
    )
  })

  // -------------------------------------------------------------------------
  // 3. 'ws_error' event dispatches STREAM_DONE + STREAM_ERROR and cleans up
  // -------------------------------------------------------------------------
  it('ws_error event dispatches STREAM_DONE and STREAM_ERROR and cleans up activeRequestsRef', async () => {
    const { dispatch, utils, ws } = await renderConnectedHook()

    let requestId!: string

    await act(async () => {
      // Fire-and-forget: we don't await the promise because ws_error rejects it
      utils.result.current.sendMessage({ message: 'hi' }).catch(() => { /* expected rejection path */ })
      await Promise.resolve()
    })

    requestId = JSON.parse(ws.sent[ws.sent.length - 1]).request_id

    const appendCall = dispatch.mock.calls.find(([a]) => a.type === 'APPEND_MESSAGE')
    const aiMsgId = (appendCall![0] as Extract<ChatAction, { type: 'APPEND_MESSAGE' }>).message.id

    dispatch.mockClear()

    await act(async () => {
      ws.receive({ type: 'ws_error', request_id: requestId, message: 'Protocol error occurred' })
    })

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_DONE', messageId: aiMsgId }),
    )
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_ERROR', error: 'Protocol error occurred' }),
    )

    // Verify cleanup: further content frames for the same request are ignored
    dispatch.mockClear()

    await act(async () => {
      ws.receive({ type: 'content', request_id: requestId, data: { delta: 'ignored' } })
    })

    expect(dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_CONTENT' }),
    )
  })

  // -------------------------------------------------------------------------
  // 4. 'interrupt' event dispatches STREAM_DONE + SET_INTERRUPT
  // -------------------------------------------------------------------------
  it('interrupt event dispatches STREAM_DONE and SET_INTERRUPT', async () => {
    const { dispatch, utils, ws } = await renderConnectedHook()

    let requestId!: string
    let sendP!: Promise<{ requestId: string }>

    await act(async () => {
      sendP = utils.result.current.sendMessage({ message: 'hi', threadId: 'thread-interrupt' })
      await Promise.resolve()
    })

    requestId = JSON.parse(ws.sent[ws.sent.length - 1]).request_id

    const appendCall = dispatch.mock.calls.find(([a]) => a.type === 'APPEND_MESSAGE')
    const aiMsgId = (appendCall![0] as Extract<ChatAction, { type: 'APPEND_MESSAGE' }>).message.id

    dispatch.mockClear()

    await act(async () => {
      ws.receive({
        type: 'interrupt',
        request_id: requestId,
        thread_id: 'thread-interrupt',
        data: {
          node_name: 'approval_node',
          node_label: 'Approval',
          state: { pending: true },
        },
      })
    })
    await sendP

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'STREAM_DONE', messageId: aiMsgId }),
    )
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'SET_INTERRUPT',
        interrupt: expect.objectContaining({
          threadId: 'thread-interrupt',
          nodeName: 'approval_node',
          nodeLabel: 'Approval',
        }),
      }),
    )
  })

  // -------------------------------------------------------------------------
  // 5. sendMessage sends a 'chat' WS frame with the correct fields
  // -------------------------------------------------------------------------
  it('sendMessage sends a chat frame with the expected fields', async () => {
    const { utils, ws } = await renderConnectedHook()

    let sendP!: Promise<{ requestId: string }>

    await act(async () => {
      sendP = utils.result.current.sendMessage({
        message: 'Hello!',
        threadId: 'thread-42',
        graphId: 'graph-1',
        metadata: { key: 'value' },
      })
      await Promise.resolve()
    })

    expect(ws.sent.length).toBeGreaterThanOrEqual(1)
    const frame = JSON.parse(ws.sent[ws.sent.length - 1])

    expect(frame).toMatchObject({
      type: 'chat',
      message: 'Hello!',
      thread_id: 'thread-42',
      graph_id: 'graph-1',
      metadata: { key: 'value' },
    })
    expect(typeof frame.request_id).toBe('string')
    expect(frame.request_id.length).toBeGreaterThan(0)

    // Clean up the dangling promise
    await act(async () => {
      ws.receive({ type: 'done', request_id: frame.request_id })
    })
    await sendP
  })
})
