'use client'

import { createContext, ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useNotificationWebSocket, NotificationMessage } from '@/hooks/use-notification-websocket'
import { taskKeys } from '@/hooks/queries/tasks'
import { taskActivityKeys } from '@/hooks/queries/taskActivities'
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
    if (type === 'task_updated' || type === 'execution_status_changed') {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
    }
    if (type === 'task_activity_added') {
      queryClient.invalidateQueries({ queryKey: taskActivityKeys.all })
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
