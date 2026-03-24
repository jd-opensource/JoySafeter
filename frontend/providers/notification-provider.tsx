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

  const handleNotification = (_notification: NotificationMessage) => {
    // Future notification types can be handled here
  }

  const { isConnected, lastNotification, reconnect, disconnect } = useNotificationWebSocket({
    userId: user?.id,
    onNotification: handleNotification,
    autoReconnect: true,
  })

  return (
    <NotificationContext.Provider value={{ isConnected, lastNotification, reconnect, disconnect }}>
      {children}
    </NotificationContext.Provider>
  )
}

export default NotificationProvider
