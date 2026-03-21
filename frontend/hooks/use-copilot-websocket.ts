'use client'

/**
 * Copilot WebSocket event types.
 * Contract: docs/schemas/copilot-contract.json (source: backend app/core/copilot/action_types.py).
 * Server sends: status | content | thought_step | tool_call | tool_result | result | done | error.
 * Client-only: pong (server response to ping).
 */

import { env as runtimeEnv } from 'next-runtime-env'
import { useEffect, useRef, useCallback, useState } from 'react'

import type { StreamGraphActionsCallbacks } from '@/services/copilotService'
import type { GraphActionType } from '@/types/copilot'

export interface CopilotWebSocketEvent {
  type:
    | 'status'
    | 'content'
    | 'thought_step'
    | 'tool_call'
    | 'tool_result'
    | 'result'
    | 'error'
    | 'done'
    | 'pong'
  stage?: string
  message?: string
  content?: string
  step?: { index: number; content: string }
  tool?: string
  input?: Record<string, unknown>
  action?: {
    type: string
    payload: Record<string, unknown>
    reasoning?: string
  }
  actions?: Array<{
    type: string
    payload: Record<string, unknown>
    reasoning?: string
  }>
  /** Present on type === 'error'. See contract for codes (e.g. CREDENTIAL_ERROR, UNKNOWN_ERROR). */
  code?: string
  /** Present on type === 'result'. Optional batch flag from backend. */
  batch?: boolean
}

export interface UseCopilotWebSocketOptions {
  sessionId: string | null
  callbacks: StreamGraphActionsCallbacks & {
    onConnect?: () => void
    onDisconnect?: () => void
    onDone?: () => void
  }
  autoReconnect?: boolean
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

function getWsBaseUrl(): string {
  const apiUrl = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  if (apiUrl) {
    return apiUrl
      .replace(/^https:/, 'wss:')
      .replace(/^http:/, 'ws:')
      .replace(/\/api\/?$/, '')
  }
  return 'ws://localhost:8000'
}

export function useCopilotWebSocket(options: UseCopilotWebSocketOptions) {
  const {
    sessionId,
    callbacks,
    autoReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
  } = options

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const heartbeatIntervalRef = useRef<NodeJS.Timeout | null>(null)
  // eslint-disable-next-line react-hooks/purity
  const lastPongRef = useRef<number>(Date.now())
  const callbacksRef = useRef(callbacks)
  const queueRef = useRef<CopilotWebSocketEvent[]>([])
  const processingRef = useRef(false)

  // Update callbacks ref when it changes
  useEffect(() => {
    callbacksRef.current = callbacks
  }, [callbacks])

  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current)
      heartbeatIntervalRef.current = null
    }
    if (wsRef.current) {
      try {
        // Remove all event handlers to prevent memory leaks
        wsRef.current.onopen = null
        wsRef.current.onmessage = null
        wsRef.current.onclose = null // Prevent triggering reconnect
        wsRef.current.onerror = null

        // Close connection if still open or connecting
        if (
          wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING
        ) {
          wsRef.current.close()
        }
      } catch {
        // Ignore close errors
      }
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) {
      cleanup()
      return
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    cleanup()

    const wsUrl = `${getWsBaseUrl()}/ws/copilot/${sessionId}`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        setError(null)
        reconnectAttemptsRef.current = 0
        lastPongRef.current = Date.now()

        // Notify connection established
        callbacksRef.current.onConnect?.()

        // Start heartbeat (ping every 30 seconds)
        heartbeatIntervalRef.current = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            const now = Date.now()
            // If no pong received in 60 seconds, consider connection dead
            if (now - lastPongRef.current > 60000) {
              console.warn('[WebSocket] Heartbeat timeout, reconnecting...')
              cleanup()
              if (autoReconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
                reconnectAttemptsRef.current++
                reconnectTimeoutRef.current = setTimeout(() => {
                  // eslint-disable-next-line react-hooks/immutability
                  connect()
                }, reconnectInterval)
              }
            } else {
              // Send ping
              try {
                wsRef.current.send(JSON.stringify({ type: 'ping' }))
              } catch (e) {
                console.error('[WebSocket] Failed to send ping:', e)
              }
            }
          }
        }, 30000)
      }

      const handleMessage = async (data: CopilotWebSocketEvent) => {
        const cbs = callbacksRef.current
        switch (data.type) {
          case 'status':
            if (data.stage && data.message) {
              cbs.onStatus(data.stage, data.message)
            }
            break
          case 'content':
            if (data.content) {
              cbs.onContent(data.content)
            }
            break
          case 'thought_step':
            if (data.step) {
              cbs.onThoughtStep?.(data.step)
            }
            break
          case 'tool_call':
            if (data.tool && data.input) {
              cbs.onToolCall(data.tool, data.input)
            }
            break
          case 'tool_result':
            if (data.action) {
              cbs.onToolResult(data.action)
            }
            break
          case 'result':
            await cbs.onResult?.({
              message: data.message ?? '',
              actions: (data.actions ?? []).map(
                (a: { type: string; payload: Record<string, unknown>; reasoning?: string }) => ({
                  type: a.type as GraphActionType,
                  payload: a.payload ?? {},
                  reasoning: a.reasoning ?? '',
                }),
              ),
            })
            break
          case 'error': {
            const errorCode = (data as { code?: string }).code
            const rawMessage = data.message ?? ''
            const messageByCode: Record<string, string> = {
              CREDENTIAL_ERROR:
                'Authentication error. Please check your API credentials in settings.',
              AGENT_ERROR: 'Agent initialization failed. Please try again or contact support.',
              CANCELLED: 'Request was cancelled.',
              REDIS_UNAVAILABLE: 'Service temporarily unavailable. Please try again later.',
              UNKNOWN_ERROR: 'An unexpected error occurred. Please try again or contact support.',
            }
            const errorMessage =
              errorCode && messageByCode[errorCode] != null
                ? messageByCode[errorCode]
                : `${rawMessage || 'An error occurred.'}`

            if (errorCode === 'CANCELLED') {
              cleanup()
              return
            }

            cbs.onError(errorMessage)
            setError(errorMessage)

            const criticalCodes = ['CREDENTIAL_ERROR', 'AGENT_ERROR', 'REDIS_UNAVAILABLE']
            if (errorCode && criticalCodes.includes(errorCode)) {
              cleanup()
            }
            break
          }
          case 'done':
            await cbs.onDone?.()
            cleanup()
            break
        }
      }

      const processQueue = async () => {
        if (processingRef.current) return
        processingRef.current = true
        while (queueRef.current.length > 0) {
          const msg = queueRef.current.shift()!
          try {
            await handleMessage(msg)
          } catch (e) {
            console.error('[WebSocket] Error processing message:', e)
          }
        }
        processingRef.current = false
      }

      ws.onmessage = (event) => {
        try {
          const data: CopilotWebSocketEvent = JSON.parse(event.data)

          if (data.type === 'pong') {
            lastPongRef.current = Date.now()
            return
          }

          queueRef.current.push(data)
          void processQueue()
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.onclose = (event) => {
        setIsConnected(false)

        // Notify disconnection
        callbacksRef.current.onDisconnect?.()

        // Clear heartbeat interval
        if (heartbeatIntervalRef.current) {
          clearInterval(heartbeatIntervalRef.current)
          heartbeatIntervalRef.current = null
        }

        // Don't reconnect if:
        // - Normal closure (1000) - session completed
        // - Max attempts reached
        // - Manual close (cleanup was called)
        const noReconnectCodes = [1000]

        // Calculate exponential backoff (cap at 30 seconds)
        const backoffDelay = Math.min(
          reconnectInterval * Math.pow(1.5, reconnectAttemptsRef.current),
          30000,
        )

        if (
          autoReconnect &&
          !noReconnectCodes.includes(event.code) &&
          reconnectAttemptsRef.current < maxReconnectAttempts &&
          wsRef.current !== null // Only reconnect if not manually cleaned up
        ) {
          reconnectAttemptsRef.current++
          console.warn(
            `[WebSocket] Reconnecting (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts}) in ${backoffDelay}ms...`,
          )
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, backoffDelay)
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          const errorMsg = 'Connection lost. Maximum reconnection attempts reached.'
          setError(errorMsg)
          callbacksRef.current.onError?.(errorMsg)
        } else if (!noReconnectCodes.includes(event.code) && wsRef.current !== null) {
          // Unexpected close code
          const errorMsg = `Connection closed unexpectedly (code: ${event.code})`
          console.error(`[WebSocket] ${errorMsg}`)
          setError(errorMsg)
        }
      }

      ws.onerror = (event) => {
        console.error('WebSocket error:', event)
        setError('WebSocket connection error')
      }
    } catch (e) {
      console.error('Failed to create WebSocket:', e)
      setError('Failed to create WebSocket connection')
    }
  }, [sessionId, autoReconnect, reconnectInterval, maxReconnectAttempts, cleanup])

  useEffect(() => {
    if (sessionId) {
      connect()
    } else {
      cleanup()
    }
    return () => cleanup()
  }, [sessionId, connect, cleanup])

  return {
    isConnected,
    error,
    reconnect: connect,
    disconnect: cleanup,
  }
}
