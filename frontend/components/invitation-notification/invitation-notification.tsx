'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Check, XCircle, Mail } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { workspaceService, type Invitation } from '@/services/workspaceService'


// Invitation type is imported from workspaceService (using PendingInvitation as alias)
type PendingInvitation = Invitation

export function InvitationNotification() {
  const { t } = useTranslation()
  const router = useRouter()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())

  const { data: invitationsData, isLoading } = useQuery<{ invitations: PendingInvitation[] }>({
    queryKey: ['workspace-invitations', 'pending'],
    queryFn: () => workspaceService.getPendingInvitations(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  // Accept invitation
  const acceptMutation = useMutation({
    mutationFn: (invitationId: string) => workspaceService.acceptInvitation(invitationId),
    onSuccess: async (data, invitationId) => {
      // Invalidate related queries
      await queryClient.invalidateQueries({ queryKey: ['workspace-invitations'] })
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['workspace'] })
      
      toast({
        title: t('workspace.invitationAccepted'),
        description: t('workspace.invitationAcceptedDescription', { workspaceName: data.workspace?.name || '' }),
      })
      
      // Navigate to workspace
      if (data.workspace?.id) {
        router.push(`/workspace/${data.workspace.id}`)
      }
    },
    onError: (error: Error) => {
      toast({
        title: t('workspace.acceptInvitationFailed'),
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  // Reject invitation
  const rejectMutation = useMutation({
    mutationFn: (invitationId: string) => workspaceService.rejectInvitation(invitationId),
    onSuccess: async (_, invitationId) => {
      // Invalidate related queries
      await queryClient.invalidateQueries({ queryKey: ['workspace-invitations'] })
      
      toast({
        title: t('workspace.invitationRejected'),
        description: t('workspace.invitationRejectedDescription'),
      })
      
      // Mark as dismissed
      setDismissedIds(prev => new Set(prev).add(invitationId))
    },
    onError: (error: Error) => {
      toast({
        title: t('workspace.rejectInvitationFailed'),
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const handleDismiss = (invitationId: string) => {
    setDismissedIds(prev => new Set(prev).add(invitationId))
  }

  const invitations = invitationsData?.invitations || []
  const visibleInvitations = invitations.filter(inv => !dismissedIds.has(inv.id))

  if (isLoading || visibleInvitations.length === 0) {
    return null
  }

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 max-w-md">
      {visibleInvitations.map((invitation) => (
        <div
          key={invitation.id}
          className="bg-white border border-gray-200 rounded-lg shadow-lg p-4 animate-in slide-in-from-top-5"
        >
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 mt-0.5">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                <Mail className="h-5 w-5 text-blue-600" />
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-gray-900">
                    {t('workspace.workspaceInvitation')}
                  </h4>
                  <p className="text-sm text-gray-600 mt-1">
                    <span className="font-medium">{invitation.inviterName || invitation.inviterEmail || t('workspace.unknown')}</span>
                    {' '}
                    {t('workspace.invitedYouToJoin')}
                    {' '}
                    <span className="font-medium">{invitation.workspaceName}</span>
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {t('workspace.role')}: {t(`workspace.roles.${invitation.role}`)}
                  </p>
                </div>
                <button
                  onClick={() => handleDismiss(invitation.id)}
                  className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex items-center gap-2 mt-3">
                <Button
                  size="sm"
                  onClick={() => acceptMutation.mutate(invitation.id)}
                  disabled={acceptMutation.isPending || rejectMutation.isPending}
                  className="flex-1"
                >
                  {acceptMutation.isPending ? (
                    <>
                      <div className="h-3 w-3 mr-2 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      {t('workspace.accepting')}
                    </>
                  ) : (
                    <>
                      <Check className="h-3 w-3 mr-1" />
                      {t('workspace.accept')}
                    </>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => rejectMutation.mutate(invitation.id)}
                  disabled={acceptMutation.isPending || rejectMutation.isPending}
                  className="flex-1"
                >
                  <XCircle className="h-3 w-3 mr-1" />
                  {t('workspace.reject')}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

