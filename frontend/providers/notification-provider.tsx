'use client'

import { createContext, useContext, ReactNode } from 'react'

import { useNotificationWebSocket, NotificationMessage, NotificationType } from '@/hooks/use-notification-websocket'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useAuthStore } from '@/stores/auth/store'

interface NotificationContextValue {
  isConnected: boolean
  lastNotification: NotificationMessage | null
  reconnect: () => void
  disconnect: () => void
}

const NotificationContext = createContext<NotificationContextValue | null>(null)

export function useNotificationContext() {
  const context = useContext(NotificationContext)
  if (!context) {
    throw new Error('useNotificationContext must be used within NotificationProvider')
  }
  return context
}

interface NotificationProviderProps {
  children: ReactNode
}

export function NotificationProvider({ children }: NotificationProviderProps) {
  const user = useAuthStore((state) => state.user)
  const { toast } = useToast()
  const { t } = useTranslation()

  const handleNotification = (notification: NotificationMessage) => {
    switch (notification.type) {
      case NotificationType.INVITATION_RECEIVED:
        toast({
          title: t('workspace.newInvitation') || 'New Invitation',
          description: `${notification.data?.inviterName || notification.data?.inviterEmail || 'Someone'} ${t('workspace.invitedYouToJoin') || 'invited you to join'} ${notification.data?.workspaceName || 'a workspace'}`,
        })
        break

      case NotificationType.INVITATION_ACCEPTED:
        toast({
          title: t('workspace.invitationAccepted') || 'Invitation Accepted',
          description: `${notification.data?.acceptedByName || notification.data?.acceptedByEmail || 'Someone'} ${t('workspace.joinedWorkspace') || 'joined'} ${notification.data?.workspaceName || 'your workspace'}`,
        })
        break

      case NotificationType.INVITATION_REJECTED:
        toast({
          title: t('workspace.invitationRejected') || 'Invitation Declined',
          description: `${notification.data?.rejectedByEmail || 'Someone'} ${t('workspace.declinedInvitation') || 'declined the invitation to'} ${notification.data?.workspaceName || 'your workspace'}`,
          variant: 'destructive',
        })
        break
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

