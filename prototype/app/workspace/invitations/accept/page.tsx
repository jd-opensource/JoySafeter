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
import { useState, Suspense, type ReactNode } from 'react'

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

function InviteShell({
  icon: Icon,
  title,
  description,
  children,
  tone = 'brand',
}: {
  icon: typeof Mail
  title: string
  description: string
  children: ReactNode
  tone?: 'brand' | 'success' | 'danger'
}) {
  const toneClass =
    tone === 'success'
      ? 'text-[var(--status-healthy)] bg-[rgba(53,111,97,0.08)] border-[rgba(53,111,97,0.16)]'
      : tone === 'danger'
        ? 'text-[var(--status-offline)] bg-[rgba(156,68,56,0.08)] border-[rgba(156,68,56,0.16)]'
        : 'text-[var(--brand-500)] bg-[rgba(36,56,77,0.08)] border-[rgba(36,56,77,0.16)]'

  return (
    <div className="executive-shell flex min-h-screen items-center justify-center p-4">
      <div className="surface-panel w-full max-w-xl px-8 py-8">
        <div className="space-y-6">
          <div className="space-y-4 text-center">
            <div className="executive-kicker mx-auto">Workspace Invitation</div>
            <div className={`mx-auto flex h-14 w-14 items-center justify-center rounded-full border ${toneClass}`}>
              <Icon className="h-6 w-6" />
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                {title}
              </h1>
              <p className="text-sm leading-6 text-[var(--text-secondary)]">
                {description}
              </p>
            </div>
          </div>
          {children}
        </div>
      </div>
    </div>
  )
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
      <InviteShell
        icon={Mail}
        title={t('workspace.invitationRequiresLogin')}
        description={t('workspace.invitationRequiresLoginDescription')}
      >
        <Button
          onClick={() => {
            router.push(`/auth/signin?callbackUrl=${encodeURIComponent(`/workspace/invitations/accept?token=${token}`)}`)
          }}
          className="btn-primary w-full rounded-full"
        >
          {t('auth.signIn')}
        </Button>
      </InviteShell>
    )
  }

  // Loading
  if (isLoadingInvitation || isSessionLoading) {
    return (
      <InviteShell
        icon={Loader2}
        title={t('workspace.loadingInvitation')}
        description={t('workspace.invitationDescription')}
      >
        <div className="text-center text-sm text-[var(--text-secondary)]">
          <Loader2 className="mx-auto mb-3 h-10 w-10 animate-spin text-[var(--brand-500)]" />
          {t('workspace.loadingInvitation')}
        </div>
      </InviteShell>
    )
  }

  // Error state
  if (invitationError || !invitation) {
    return (
      <InviteShell
        icon={XCircle}
        title={t('workspace.invitationInvalid')}
        description={invitationError instanceof Error
          ? invitationError.message
          : t('workspace.invitationInvalidDescription')}
        tone="danger"
      >
        <Button
          variant="outline"
          onClick={() => router.push('/workspace')}
          className="w-full rounded-full"
        >
          {t('workspace.backToWorkspace')}
        </Button>
      </InviteShell>
    )
  }

  // Check if email matches
  const emailMatches = session?.user?.email?.toLowerCase() === invitation.email.toLowerCase()

  return (
    <InviteShell
      icon={CheckCircle}
      title={t('workspace.workspaceInvitation')}
      description={t('workspace.invitationDescription')}
      tone="success"
    >
      <div className="space-y-4">
        <div className="surface-panel-flat p-4">
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[rgba(54,93,130,0.16)] bg-[rgba(54,93,130,0.08)]">
              <Users className="h-5 w-5 text-[var(--status-running)]" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold text-[var(--text-primary)]">{invitation.workspaceName}</p>
              <p className="text-xs text-[var(--text-secondary)]">{t('workspace.workspace')}</p>
            </div>
          </div>
        </div>

        <div className="surface-panel-flat space-y-3 p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">{t('workspace.invitedBy')}</span>
            <span className="font-medium text-[var(--text-primary)]">
              {invitation.inviterName || invitation.inviterEmail || t('workspace.unknown')}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">{t('workspace.role')}</span>
            <div className="flex items-center gap-2">
              <RoleIcon className="h-4 w-4 text-[var(--text-muted)]" />
              <span className="font-medium text-[var(--text-primary)]">
                {t(`workspace.roles.${invitation.role}`)}
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-[var(--text-secondary)]">{t('workspace.email')}</span>
            <span className="font-medium text-[var(--text-primary)]">{invitation.email}</span>
          </div>
        </div>

        {!emailMatches && (
          <div className="rounded-[1rem] border border-[rgba(155,106,45,0.16)] bg-[rgba(155,106,45,0.08)] p-3">
            <p className="text-sm leading-6 text-[var(--warning)]">
              {t('workspace.emailMismatch', {
                invitationEmail: invitation.email,
                currentEmail: session?.user?.email || ''
              })}
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Button
            onClick={handleAccept}
            disabled={isAccepting || !emailMatches}
            className="btn-primary w-full rounded-full"
          >
            {isAccepting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('workspace.accepting')}
              </>
            ) : (
              <>
                <CheckCircle className="mr-2 h-4 w-4" />
                {t('workspace.acceptInvitation')}
              </>
            )}
          </Button>
          <Button
            variant="outline"
            onClick={() => router.push('/workspace')}
            className="w-full rounded-full"
          >
            {t('workspace.cancel')}
          </Button>
        </div>
      </div>
    </InviteShell>
  )
}

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={
      <InviteShell
        icon={Loader2}
        title="Loading..."
        description="Preparing invitation details."
      >
        <div className="text-center text-sm text-[var(--text-secondary)]">
          <Loader2 className="mx-auto mb-3 h-10 w-10 animate-spin text-[var(--brand-500)]" />
          Loading...
        </div>
      </InviteShell>
    }>
      <AcceptInvitationContent />
    </Suspense>
  )
}
