'use client'

/**
 * Workspace Invitation Acceptance Page
 *
 * Features:
 * - Display invitation information based on token
 * - Validate invitation validity
 * - Accept invitation and join workspace
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, CheckCircle, XCircle, Loader2, Mail, Shield, Crown, Eye, Edit } from 'lucide-react'
import { useSearchParams, useRouter } from 'next/navigation'
import { useState, Suspense } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { workspaceService, type Invitation } from '@/services/workspaceService'

// Invitation type imported from workspaceService (using InvitationInfo as alias)
type InvitationInfo = Invitation

const ROLE_ICONS = {
  owner: Crown,
  admin: Shield,
  member: Edit,
  viewer: Eye,
}

function AcceptInvitationContent() {
  const { t } = useTranslation()
  const searchParams = useSearchParams()
  const router = useRouter()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { data: session, isPending: isSessionLoading } = useSession()

  const token = searchParams.get('token')
  const [isAccepting, setIsAccepting] = useState(false)

  // Get invitation information
  const { data: invitationData, isLoading: isLoadingInvitation, error: invitationError } = useQuery<{ success: boolean; invitation: InvitationInfo }>({
    queryKey: ['invitation', token],
    queryFn: async () => {
      if (!token) {
        throw new Error('Token is required')
      }
      return workspaceService.getInvitation(token)
    },
    enabled: !!token,
    retry: false,
  })

  // Accept invitation
  const acceptMutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error('Token is required')
      }
      return workspaceService.acceptInvitation(token)
    },
    onSuccess: async (data) => {
      // Invalidate workspace list query to ensure newly joined workspace appears in the list
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['workspace'] })

      toast({
        title: t('workspace.invitationAccepted'),
        description: t('workspace.invitationAcceptedDescription', { workspaceName: data.workspace?.name || '' }),
      })
      // Navigate to workspace
      if (data.workspace?.id) {
        router.push(`/workspace/${data.workspace.id}`)
      } else {
        router.push('/workspace')
      }
    },
    onError: (error: Error) => {
      toast({
        title: t('workspace.acceptInvitationFailed'),
        description: error.message,
        variant: 'destructive',
      })
      setIsAccepting(false)
    },
  })

  const handleAccept = () => {
    if (!session?.user) {
      // If not logged in, redirect to login page
      router.push(`/auth/signin?callbackUrl=${encodeURIComponent(`/workspace/invitations/accept?token=${token}`)}`)
      return
    }
    setIsAccepting(true)
    acceptMutation.mutate()
  }

  const invitation = invitationData?.invitation
  const RoleIcon = invitation ? ROLE_ICONS[invitation.role as keyof typeof ROLE_ICONS] || Shield : Shield

  // If not logged in, show prompt
  if (!isSessionLoading && !session?.user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-lg">
          <div className="text-center">
            <Mail className="mx-auto h-12 w-12 text-blue-600 mb-4" />
            <h1 className="text-2xl font-semibold text-gray-900 mb-2">
              {t('workspace.invitationRequiresLogin')}
            </h1>
            <p className="text-sm text-gray-500 mb-6">
              {t('workspace.invitationRequiresLoginDescription')}
            </p>
            <Button
              onClick={() => {
                router.push(`/auth/signin?callbackUrl=${encodeURIComponent(`/workspace/invitations/accept?token=${token}`)}`)
              }}
              className="w-full"
            >
              {t('auth.signIn')}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Loading
  if (isLoadingInvitation || isSessionLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <Loader2 className="mx-auto h-12 w-12 animate-spin text-blue-600 mb-4" />
          <p className="text-sm text-gray-500">{t('workspace.loadingInvitation')}</p>
        </div>
      </div>
    )
  }

  // Error state
  if (invitationError || !invitation) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
        <div className="w-full max-w-md rounded-lg border border-red-200 bg-white p-8 shadow-lg">
          <div className="text-center">
            <XCircle className="mx-auto h-12 w-12 text-red-600 mb-4" />
            <h1 className="text-2xl font-semibold text-gray-900 mb-2">
              {t('workspace.invitationInvalid')}
            </h1>
            <p className="text-sm text-gray-500 mb-6">
              {invitationError instanceof Error
                ? invitationError.message
                : t('workspace.invitationInvalidDescription')}
            </p>
            <Button
              variant="outline"
              onClick={() => router.push('/workspace')}
            >
              {t('workspace.backToWorkspace')}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Check if email matches
  const emailMatches = session?.user?.email?.toLowerCase() === invitation.email.toLowerCase()

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-lg">
        <div className="text-center mb-6">
          <CheckCircle className="mx-auto h-12 w-12 text-green-600 mb-4" />
          <h1 className="text-2xl font-semibold text-gray-900 mb-2">
            {t('workspace.workspaceInvitation')}
          </h1>
          <p className="text-sm text-gray-500">
            {t('workspace.invitationDescription')}
          </p>
        </div>

        {/* Invitation Information */}
        <div className="space-y-4 mb-6">
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                <Users className="h-5 w-5 text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-900 truncate">{invitation.workspaceName}</p>
                <p className="text-xs text-gray-500">{t('workspace.workspace')}</p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">{t('workspace.invitedBy')}</span>
              <span className="font-medium text-gray-900">
                {invitation.inviterName || invitation.inviterEmail || t('workspace.unknown')}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">{t('workspace.role')}</span>
              <div className="flex items-center gap-2">
                <RoleIcon className="h-4 w-4 text-gray-400" />
                <span className="font-medium text-gray-900">
                  {t(`workspace.roles.${invitation.role}`)}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">{t('workspace.email')}</span>
              <span className="font-medium text-gray-900">{invitation.email}</span>
            </div>
          </div>

          {/* Email Match Check */}
          {!emailMatches && (
            <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
              <p className="text-sm text-yellow-800">
                {t('workspace.emailMismatch', {
                  invitationEmail: invitation.email,
                  currentEmail: session?.user?.email || ''
                })}
              </p>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="space-y-2">
          <Button
            onClick={handleAccept}
            disabled={isAccepting || !emailMatches}
            className="w-full"
          >
            {isAccepting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {t('workspace.accepting')}
              </>
            ) : (
              <>
                <CheckCircle className="h-4 w-4 mr-2" />
                {t('workspace.acceptInvitation')}
              </>
            )}
          </Button>
          <Button
            variant="outline"
            onClick={() => router.push('/workspace')}
            className="w-full"
          >
            {t('workspace.cancel')}
          </Button>
        </div>
      </div>
    </div>
  )
}

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <Loader2 className="mx-auto h-12 w-12 animate-spin text-blue-600 mb-4" />
          <p className="text-sm text-gray-500">Loading...</p>
        </div>
      </div>
    }>
      <AcceptInvitationContent />
    </Suspense>
  )
}
