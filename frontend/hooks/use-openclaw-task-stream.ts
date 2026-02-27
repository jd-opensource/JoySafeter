'use client'

import { env as runtimeEnv } from 'next-runtime-env'
import { useCallback, useEffect, useRef, useState } from 'react'

function getWsBaseUrl(): string {
  const apiUrl = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  if (apiUrl) {
    return apiUrl.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:').replace(/\/api\/?$/, '')
  }
  return 'ws://localhost:8000'
}

function getAuthCookie(): string | null {
  if (typeof document === 'undefined') return null
  for (const c of document.cookie.split(';')) {
    const [name, value] = c.trim().split('=')
    if (name === 'auth_token') return value
  }
  return null
}

export interface OpenClawStreamEvent {
  type: 'output' | 'done' | 'error' | 'cancelled' | 'pong'
  data?: string
  message?: string
}

export function useOpenClawTaskStream(taskId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const heartbeatRef = useRef<NodeJS.Timeout | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [chunks, setChunks] = useState<string[]>([])
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const cleanup = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
    }
    if (wsRef.current) {
      try {
        wsRef.current.onopen = null
        wsRef.current.onmessage = null
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        if (
          wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING
        ) {
          wsRef.current.close()
        }
      } catch {
        /* ignore */
      }
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  const connect = useCallback(() => {
    if (!taskId) {
      cleanup()
      return
    }
    cleanup()
    setChunks([])
    setFinished(false)
    setError(null)

    const wsUrl = `${getWsBaseUrl()}/ws/openclaw/${taskId}`
    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        heartbeatRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({ type: 'ping' }))
            } catch {
              /* ignore */
            }
          }
        }, 30_000)
      }

      ws.onmessage = (event) => {
        try {
          const ev: OpenClawStreamEvent = JSON.parse(event.data)
          if (ev.type === 'pong') return

          if (ev.type === 'output' && ev.data) {
            setChunks((prev) => [...prev, ev.data!])
          } else if (ev.type === 'done') {
            setFinished(true)
            cleanup()
          } else if (ev.type === 'error') {
            setError(ev.message ?? 'Task failed')
            setFinished(true)
            cleanup()
          } else if (ev.type === 'cancelled') {
            setFinished(true)
            cleanup()
          }
        } catch {
          /* ignore unparseable messages */
        }
      }

      ws.onclose = () => {
        setIsConnected(false)
      }
      ws.onerror = () => {
        setError('WebSocket connection error')
      }
    } catch {
      setError('Failed to open WebSocket')
    }
  }, [taskId, cleanup])

  useEffect(() => {
    if (taskId) {
      connect()
    } else {
      cleanup()
    }
    return () => cleanup()
  }, [taskId, connect, cleanup])

  return { isConnected, chunks, output: chunks.join(''), finished, error, reconnect: connect }
}
