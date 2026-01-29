'use client'

import { useQueryClient } from '@tanstack/react-query'
import { env as runtimeEnv } from 'next-runtime-env'
import { useEffect, useRef, useCallback, useState } from 'react'

export enum NotificationType {
  INVITATION_RECEIVED = 'invitation_received',
  INVITATION_ACCEPTED = 'invitation_accepted',
  INVITATION_REJECTED = 'invitation_rejected',
  INVITATION_CANCELLED = 'invitation_cancelled',
  PING = 'ping',
  PONG = 'pong',
  CONNECTED = 'connected',
}

export interface NotificationMessage {
  type: NotificationType
  data?: any
  message?: string
  timestamp?: string
}

export interface UseNotificationWebSocketOptions {
  userId: string | null | undefined
  onNotification?: (notification: NotificationMessage) => void
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

export function useNotificationWebSocket(options: UseNotificationWebSocketOptions) {
  const {
    userId,
    onNotification,
    autoReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
  } = options

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const queryClient = useQueryClient()

  const [isConnected, setIsConnected] = useState(false)
  const [lastNotification, setLastNotification] = useState<NotificationMessage | null>(null)

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }
    if (wsRef.current) {
      // Remove all event handlers to prevent memory leaks
      wsRef.current.onopen = null
      wsRef.current.onmessage = null
      wsRef.current.onclose = null
      wsRef.current.onerror = null
      
      // Close connection if still open or connecting
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close()
      }
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  // Use ref to store onNotification callback to avoid dependency issues
  const onNotificationRef = useRef(onNotification)
  useEffect(() => {
    onNotificationRef.current = onNotification
  }, [onNotification])

  const connect = useCallback(() => {
    if (!userId) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    cleanup()

    const wsUrl = `${getWsBaseUrl()}/ws/notifications`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        reconnectAttemptsRef.current = 0

        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      ws.onmessage = (event) => {
        try {
          const notification: NotificationMessage = JSON.parse(event.data)
          setLastNotification(notification)

          switch (notification.type) {
            case NotificationType.INVITATION_RECEIVED:
              queryClient.invalidateQueries({ queryKey: ['workspace-invitations', 'pending'] })
              break
            case NotificationType.INVITATION_ACCEPTED:
            case NotificationType.INVITATION_REJECTED:
              queryClient.invalidateQueries({ queryKey: ['workspace-invitations'] })
              queryClient.invalidateQueries({ queryKey: ['workspaces'] })
              break
          }

          onNotificationRef.current?.(notification)
        } catch {
          // Ignore parse errors
        }
      }

      ws.onclose = (event) => {
        setIsConnected(false)

        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = null
        }

        const noReconnectCodes = [1000, 4001, 4003]
        
        if (autoReconnect && !noReconnectCodes.includes(event.code) && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current++
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        }
      }

      ws.onerror = () => {}
    } catch {
      // Ignore connection errors
    }
  }, [userId, autoReconnect, reconnectInterval, maxReconnectAttempts, cleanup, queryClient])

  useEffect(() => {
    if (userId) {
      connect()
    } else {
      cleanup()
    }
    return () => cleanup()
  }, [userId, connect, cleanup])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && userId) {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          connect()
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [userId, connect])

  return {
    isConnected,
    lastNotification,
    reconnect: connect,
    disconnect: cleanup,
  }
}

export default useNotificationWebSocket

