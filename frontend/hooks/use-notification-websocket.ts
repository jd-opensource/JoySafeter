'use client'

import { useEffect, useRef, useCallback, useState } from 'react'

import { NotificationWsClient } from '@/lib/ws/notifications/NotificationWsClient'
import type { NotificationMessage } from '@/lib/ws/notifications/NotificationWsClient'

export type { NotificationMessage } from '@/lib/ws/notifications/NotificationWsClient'

export enum NotificationType {
  PING = 'ping',
  PONG = 'pong',
  CONNECTED = 'connected',
}

export interface UseNotificationWebSocketOptions {
  userId: string | null | undefined
  onNotification?: (notification: NotificationMessage) => void
  autoReconnect?: boolean
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

export function useNotificationWebSocket(options: UseNotificationWebSocketOptions) {
  const { userId, onNotification, autoReconnect = true } = options
  const clientRef = useRef<NotificationWsClient | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [lastNotification, setLastNotification] = useState<NotificationMessage | null>(null)

  const onNotificationRef = useRef(onNotification)
  useEffect(() => {
    onNotificationRef.current = onNotification
  }, [onNotification])

  const unsubRef = useRef<(() => void) | null>(null)

  const getClient = useCallback(() => {
    if (!clientRef.current) {
      clientRef.current = new NotificationWsClient()
    }
    return clientRef.current
  }, [])

  const cleanup = useCallback(() => {
    unsubRef.current?.()
    unsubRef.current = null
    if (clientRef.current) {
      clientRef.current.setNotificationHandler(null)
      clientRef.current.disconnect()
      clientRef.current = null
    }
    setIsConnected(false)
    setLastNotification(null)
  }, [])

  const connect = useCallback(() => {
    if (!userId) return
    const client = getClient()

    client.setNotificationHandler((notification) => {
      setLastNotification(notification)
      onNotificationRef.current?.(notification)
    })

    if (!unsubRef.current) {
      unsubRef.current = client.subscribeConnectionState((state) => {
        setIsConnected(state.isConnected)
      })
    }

    void client.connect().catch(() => {})
  }, [userId, getClient])

  useEffect(() => {
    if (userId && autoReconnect) {
      connect()
    } else {
      cleanup()
    }
    return () => cleanup()
  }, [userId, autoReconnect, connect, cleanup])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && userId && autoReconnect) {
        const client = clientRef.current
        if (!client || !client.getConnectionState().isConnected) {
          connect()
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [userId, autoReconnect, connect])

  return {
    isConnected,
    lastNotification,
    reconnect: connect,
    disconnect: cleanup,
  }
}

export default useNotificationWebSocket
