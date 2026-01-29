'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Check, XCircle, Mail, Bell, CheckCircle2, Clock } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Pagination } from '@/components/ui/pagination'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { workspaceService, type Invitation, type PaginatedInvitationsResponse } from '@/services/workspaceService'

// Invitation and PaginatedInvitationsResponse types are imported from workspaceService

interface NotificationCenterProps {
  children?: React.ReactNode
}

export function NotificationCenter({ children }: NotificationCenterProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<'all' | 'pending' | 'processed'>('all')
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10) // Display 10 items per page

  // Reset page number when filter changes
  const handleFilterChange = (newFilter: typeof filter) => {
    setFilter(newFilter)
    setPage(1)
  }

  // Fetch paginated invitation data
  const { data: invitationsData, isLoading } = useQuery<PaginatedInvitationsResponse>({
    queryKey: ['workspace-invitations', 'all', filter, page, pageSize],
    queryFn: () => {
      const status = filter === 'pending' ? 'pending'
                   : filter === 'processed' ? 'processed'
                   : undefined
      return workspaceService.getAllInvitations({ page, pageSize, status })
    },
    enabled: open, // Only fetch when opened
    refetchInterval: open ? 30000 : false, // Refresh every 30 seconds when opened
  })

  // Fetch pending message count separately (for badge display)
  const { data: pendingCountData } = useQuery<PaginatedInvitationsResponse>({
    queryKey: ['workspace-invitations', 'pending-count'],
    queryFn: () => workspaceService.getAllInvitations({ page: 1, pageSize: 1, status: 'pending' }),
    staleTime: 30000, // Don't refetch within 30 seconds
  })

  // Fetch processed message count separately (for tab badge display)
  const { data: processedCountData } = useQuery<PaginatedInvitationsResponse>({
    queryKey: ['workspace-invitations', 'processed-count'],
    queryFn: () => workspaceService.getAllInvitations({ page: 1, pageSize: 1, status: 'processed' }),
    staleTime: 30000, // Don't refetch within 30 seconds
    enabled: open, // Only fetch when opened
  })

  // Fetch all message count separately (for tab badge display)
  const { data: allCountData } = useQuery<PaginatedInvitationsResponse>({
    queryKey: ['workspace-invitations', 'all-count'],
    queryFn: () => workspaceService.getAllInvitations({ page: 1, pageSize: 1 }),
    staleTime: 30000, // Don't refetch within 30 seconds
    enabled: open, // Only fetch when opened
  })

  // Accept invitation
  const acceptMutation = useMutation({
    mutationFn: (invitationId: string) => workspaceService.acceptInvitation(invitationId),
    onSuccess: async (data, invitationId) => {
      await queryClient.invalidateQueries({ queryKey: ['workspace-invitations'] })
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['workspace'] })

      toast({
        title: t('workspace.invitationAccepted'),
        description: t('workspace.invitationAcceptedDescription', { workspaceName: data.workspace?.name || '' }),
      })

      if (data.workspace?.id) {
        router.push(`/workspace/${data.workspace.id}`)
        setOpen(false)
      } else {
        // If still on current page, reset to first page
        setPage(1)
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
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspace-invitations'] })

      toast({
        title: t('workspace.invitationRejected'),
        description: t('workspace.invitationRejectedDescription'),
      })

      // Reset to first page
      setPage(1)
    },
    onError: (error: Error) => {
      toast({
        title: t('workspace.rejectInvitationFailed'),
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const invitations = invitationsData?.items || []
  const pendingCount = pendingCountData?.total || 0
  const processedCount = processedCountData?.total || 0
  const allCount = allCountData?.total || 0

  const getStatusBadge = (invitation: Invitation) => {
    if (invitation.isExpired) {
      return (
        <Badge variant="outline" className="bg-gray-100 text-gray-600">
          <Clock className="h-3 w-3 mr-1" />
          {t('notifications.expired')}
        </Badge>
      )
    }
    if (invitation.status === 'accepted') {
      return (
        <Badge variant="outline" className="bg-green-100 text-green-700">
          <CheckCircle2 className="h-3 w-3 mr-1" />
          {t('notifications.accepted')}
        </Badge>
      )
    }
    if (invitation.status === 'rejected') {
      return (
        <Badge variant="outline" className="bg-red-100 text-red-700">
          <XCircle className="h-3 w-3 mr-1" />
          {t('notifications.rejected')}
        </Badge>
      )
    }
    return (
      <Badge variant="outline" className="bg-blue-100 text-blue-700">
        <Clock className="h-3 w-3 mr-1" />
        {t('notifications.pending')}
      </Badge>
    )
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        {children || (
          <Button variant="ghost" size="icon" className="relative">
            <Bell className="h-5 w-5" />
            {pendingCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
                {pendingCount > 9 ? '9+' : pendingCount}
              </span>
            )}
          </Button>
        )}
      </SheetTrigger>
      {/* Remove default sidebar border to keep content area clean */}
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto border-0 shadow-none">
        <SheetHeader>
          <SheetTitle>{t('notifications.title')}</SheetTitle>
          <SheetDescription>
            {t('notifications.description')}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6">
          <Tabs value={filter} onValueChange={(v) => handleFilterChange(v as typeof filter)}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="all">
                {t('notifications.all')}
                {allCount > 0 && (
                  <Badge variant="secondary" className="ml-2">
                    {allCount}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="pending">
                {t('notifications.pending')}
                {pendingCount > 0 && (
                  <Badge variant="destructive" className="ml-2">
                    {pendingCount}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="processed">
                {t('notifications.processed')}
                {processedCount > 0 && (
                  <Badge variant="secondary" className="ml-2">
                    {processedCount}
                  </Badge>
                )}
              </TabsTrigger>
            </TabsList>

            <TabsContent value={filter} className="mt-4" data-notification-content>
              {isLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="h-6 w-6 border-2 border-gray-300 border-t-blue-600 rounded-full animate-spin" />
                </div>
              ) : invitations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Bell className="h-12 w-12 text-gray-300 mb-4" />
                  <p className="text-sm text-gray-500">
                    {filter === 'pending'
                      ? t('notifications.noPending')
                      : filter === 'processed'
                      ? t('notifications.noProcessed')
                      : t('notifications.noNotifications')}
                  </p>
                </div>
              ) : (
                <>
                  <div className="space-y-3">
                    {invitations.map((invitation) => (
                    <div
                      key={invitation.id}
                      className={cn(
                        "rounded-lg p-4 transition-colors",
                        invitation.status === 'pending' && !invitation.isExpired
                          ? "bg-blue-50"
                          : "bg-gray-50"
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div className="flex-shrink-0 mt-0.5">
                          <div className={cn(
                            "flex h-10 w-10 items-center justify-center rounded-full",
                            invitation.status === 'pending' && !invitation.isExpired
                              ? "bg-blue-100"
                              : "bg-gray-100"
                          )}>
                            <Mail className={cn(
                              "h-5 w-5",
                              invitation.status === 'pending' && !invitation.isExpired
                                ? "text-blue-600"
                                : "text-gray-400"
                            )} />
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2 mb-2">
                            <div className="flex-1">
                              <h4 className="text-sm font-semibold text-gray-900">
                                {t('workspace.workspaceInvitation')}
                              </h4>
                              <p className="text-sm text-gray-600 mt-1">
                                <span className="font-medium">
                                  {invitation.inviterName || invitation.inviterEmail || t('workspace.unknown')}
                                </span>
                                {' '}
                                {t('workspace.invitedYouToJoin')}
                                {' '}
                                <span className="font-medium">{invitation.workspaceName}</span>
                              </p>
                              <p className="text-xs text-gray-500 mt-1">
                                {t('workspace.role')}: {t(`workspace.roles.${invitation.role}`)}
                              </p>
                            </div>
                            {getStatusBadge(invitation)}
                          </div>

                          {invitation.status === 'pending' && !invitation.isExpired && (
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
                          )}

                          <p className="text-xs text-gray-400 mt-2">
                            {new Date(invitation.createdAt).toLocaleString()}
                          </p>
                        </div>
                      </div>
                    </div>
                    ))}
                  </div>

                  {/* Pagination component - display as long as there's data, even if only one page */}
                  {invitationsData && invitationsData.total !== undefined && invitationsData.total > 0 && (
                    <div className="mt-6 pt-4 border-t border-gray-200">
                      <Pagination
                        page={invitationsData.page ?? page}
                        totalPages={Math.max(invitationsData.pages ?? 1, 1)}
                        total={invitationsData.total}
                        pageSize={invitationsData.page_size ?? pageSize}
                        isLoading={isLoading}
                        onPageChange={(newPage) => {
                          setPage(newPage)
                          // Scroll to top
                          const content = document.querySelector('[data-notification-content]')
                          if (content) {
                            content.scrollTop = 0
                          }
                        }}
                      />
                    </div>
                  )}
                </>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  )
}
