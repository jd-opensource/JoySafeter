'use client'

import { createContext, ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useNotificationWebSocket, NotificationMessage } from '@/hooks/use-notification-websocket'
import { missionKeys } from '@/hooks/queries/missions'
import { missionCommentKeys } from '@/hooks/queries/missionComments'
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

  const queryClient = useQueryClient()

  const handleNotification = (notification: NotificationMessage) => {
    const { type } = notification
    if (type === 'mission_updated' || type === 'execution_status_changed') {
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    }
    if (type === 'mission_comment_added') {
      queryClient.invalidateQueries({ queryKey: missionCommentKeys.all })
    }
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
