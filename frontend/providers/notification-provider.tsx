'use client'

import { createContext, ReactNode } from 'react'

import { useNotificationWebSocket, NotificationMessage } from '@/hooks/use-notification-websocket'
import { useAuthStore } from '@/stores/auth/store'

interface NotificationContextValue {
  isConnected: boolean
  lastNotification: NotificationMessage | null
  reconnect: () => void
  disconnect: () => void
}

const NotificationContext = createContext<NotificationContextValue | null>(null)

interface NotificationProviderProps {
  children: ReactNode
}

export function NotificationProvider({ children }: NotificationProviderProps) {
  const user = useAuthStore((state) => state.user)

  // The original handler invalidated task / task_activity query caches on
  // notification messages. Those query hooks were removed along with the v1
  // platform UI, so the handler is now a no-op. We keep the WebSocket wired
  // up because the connection itself drives some UI state elsewhere; the
  // notification stream just doesn't have a consumer right now.
  const { isConnected, lastNotification, reconnect, disconnect } = useNotificationWebSocket({
    userId: user?.id,
    onNotification: () => {
      // intentionally empty — see comment above
    },
    autoReconnect: true,
  })

  return (
    <NotificationContext.Provider value={{ isConnected, lastNotification, reconnect, disconnect }}>
      {children}
    </NotificationContext.Provider>
  )
}

export default NotificationProvider
