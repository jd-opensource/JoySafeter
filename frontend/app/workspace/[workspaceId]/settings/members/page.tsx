'use client'

/**
 * Workspace Member Management Page
 *
 * Features:
 * - View member list
 * - Update member role
 * - Invite new members
 * - Remove member
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDate } from 'date-fns'
import { Users, UserPlus, Shield, Crown, Eye, Edit, Trash2, Loader2, Check } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState, useEffect, useRef } from 'react'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import {
  workspaceService,
  type PaginatedMembersResponse,
} from '@/services/workspaceService'
import { useSidebarStore } from '@/stores/sidebar/store'

// WorkspaceMember and PaginatedMembersResponse types imported from workspaceService

const ROLE_ICONS = {
  owner: Crown,
  admin: Shield,
  member: Edit,
  viewer: Eye,
}

const MEMBERS_PAGE_SIZE = 10

export default function WorkspaceMembersPage() {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params?.workspaceId as string
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const { permissions, loading: permissionsLoading, refetch } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

  // Get sidebar state to adjust layout
  const isSidebarCollapsed = useSidebarStore((state) => state.isCollapsed)

  const [inviteDialogOpen, setInviteDialogOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member' | 'viewer'>('member')
  const [removeMemberId, setRemoveMemberId] = useState<string | null>(null)
  const [updateMemberId, setUpdateMemberId] = useState<string | null>(null)
  const [updateRole, setUpdateRole] = useState<'admin' | 'member' | 'viewer' | null>(null)
  const [emailSearchQuery, setEmailSearchQuery] = useState('')
  const [emailPopoverOpen, setEmailPopoverOpen] = useState(false)
  const emailInputRef = useRef<HTMLInputElement>(null)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(MEMBERS_PAGE_SIZE)

  const { data: membersData, isLoading: membersLoading } = useQuery<PaginatedMembersResponse>({
    queryKey: ['workspace-members', workspaceId, page, pageSize],
    queryFn: () => workspaceService.getMembers(workspaceId, { page, pageSize }),
    enabled: !!workspaceId && userPermissions.canRead,
  })

  const { data: searchResults, isLoading: isSearching } = useQuery<{
    users: Array<{ id: string; email: string; name: string | null; image: string | null }>
  }>({
    queryKey: ['search-users', workspaceId, emailSearchQuery],
    queryFn: () => workspaceService.searchUsers(workspaceId, emailSearchQuery, 10),
    enabled:
      !!workspaceId &&
      !!emailSearchQuery &&
      emailSearchQuery.length >= 2 &&
      userPermissions.canAdmin,
    staleTime: 5000,
  })

  useEffect(() => {
    const timer = setTimeout(() => {
      setEmailSearchQuery(inviteEmail)
    }, 300)

    return () => clearTimeout(timer)
  }, [inviteEmail])

  const addMemberMutation = useMutation({
    mutationFn: async ({ email, role }: { email: string; role: string }) => {
      return workspaceService.addMember(workspaceId, email, role)
    },
    onSuccess: () => {
      toastSuccess(
        t('workspace.memberAddedDescription', { email: inviteEmail }),
        t('workspace.memberAdded'),
      )
      setInviteDialogOpen(false)
      setInviteEmail('')
      setInviteRole('member')
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] })
      setPage(1)
      refetch()
    },
    onError: (error: any) => {
      const rawMessage = error?.message || error?.detail || String(error) || ''
      const errorMessage = rawMessage.toLowerCase()

      const isAlreadyMember =
        errorMessage.includes('already a member') || errorMessage.includes('is already a member')

      const isUserNotFound =
        errorMessage.includes('user not found') || errorMessage.includes('not found')

      if (isAlreadyMember) {
        toastError(
          t('workspace.userAlreadyMemberDescription', { email: inviteEmail }),
          t('workspace.userAlreadyMember'),
        )
      } else if (isUserNotFound) {
        toastError(t('workspace.userNotFoundDescription'), t('workspace.userNotFound'))
      } else {
        toastError(rawMessage || t('workspace.addMemberFailed'), t('workspace.addMemberFailed'))
      }
    },
  })

  const updateRoleMutation = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      return workspaceService.updateMemberRole(workspaceId, userId, role)
    },
    onSuccess: () => {
      toast({
        title: t('workspace.roleUpdated'),
        description: t('workspace.roleUpdatedDescription'),
      })
      setUpdateMemberId(null)
      setUpdateRole(null)
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] })
      setPage(1)
      refetch()
    },
    onError: (error: any) => {
      const status = error?.status || error?.response?.status
      if (status === 403) {
        toast({
          title: t('workspace.updateFailed'),
          description: t('workspace.insufficientPermission'),
          variant: 'destructive',
        })
        refetch()
        return
      }
      toast({
        title: t('workspace.updateFailed'),
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: async (userId: string) => {
      return workspaceService.removeMember(workspaceId, userId)
    },
    onSuccess: () => {
      toast({
        title: t('workspace.memberRemoved'),
        description: t('workspace.memberRemovedDescription'),
      })
      setRemoveMemberId(null)
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] })
      setPage(1)
      refetch()
    },
    onError: (error: any) => {
      const status = error?.status || error?.response?.status
      if (status === 403) {
        toast({
          title: t('workspace.removeFailed'),
          description: t('workspace.insufficientPermission'),
          variant: 'destructive',
        })
        refetch()
        return
      }
      toast({
        title: t('workspace.removeFailed'),
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const handleInvite = () => {
    if (!inviteEmail.trim()) {
      toast({
        title: t('workspace.enterEmail'),
        variant: 'destructive',
      })
      return
    }
    addMemberMutation.mutate({ email: inviteEmail.trim(), role: inviteRole })
  }

  const handleUpdateRole = (userId: string, role: 'admin' | 'member' | 'viewer') => {
    updateRoleMutation.mutate({ userId, role })
  }

  const handleRemoveMember = (userId: string) => {
    removeMemberMutation.mutate(userId)
  }

  const members = membersData?.items || []
  const totalMembers = membersData?.total || 0
  const totalPages = membersData?.pages || 0

  if (permissionsLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  if (!userPermissions.canRead) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Shield className="mx-auto mb-4 h-12 w-12 text-[var(--text-muted)]" />
          <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">{t('workspace.noAccess')}</h2>
          <p className="text-xs text-[var(--text-tertiary)]">{t('workspace.noAccessDescription')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4 transition-all duration-300"
        style={{
          marginLeft: isSidebarCollapsed ? '280px' : '0px',
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Users className="h-6 w-6 text-[var(--text-secondary)]" />
            <h1 className="text-base font-semibold text-[var(--text-primary)]">
              {t('workspace.membersManagement')}
            </h1>
          </div>
          {userPermissions.canAdmin && (
            <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
              <DialogTrigger asChild>
                <Button>
                  <UserPlus className="mr-2 h-4 w-4" />
                  {t('workspace.addMember')}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t('workspace.addNewMember')}</DialogTitle>
                  <DialogDescription>{t('workspace.addMemberDescription')}</DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div>
                    <label className="mb-2 block text-xs font-medium text-[var(--text-secondary)]">
                      {t('workspace.emailAddress')}
                    </label>
                    <div className="relative">
                      <Input
                        ref={emailInputRef}
                        type="email"
                        placeholder="user@example.com"
                        value={inviteEmail}
                        onChange={(e) => {
                          setInviteEmail(e.target.value)
                          setEmailPopoverOpen(e.target.value.length >= 2)
                        }}
                        onFocus={() => {
                          if (inviteEmail.length >= 2) {
                            setEmailPopoverOpen(true)
                          }
                        }}
                        onBlur={() => {
                          setTimeout(() => {
                            if (!emailInputRef.current?.contains(document.activeElement)) {
                              setEmailPopoverOpen(false)
                            }
                          }, 200)
                        }}
                        className="w-full"
                      />
                      {emailPopoverOpen && (
                        <div
                          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] shadow-lg"
                          onMouseDown={(e) => {
                            e.preventDefault()
                          }}
                        >
                          {isSearching ? (
                            <div className="flex items-center justify-center py-6">
                              <Loader2 className="h-4 w-4 animate-spin text-[var(--text-muted)]" />
                            </div>
                          ) : searchResults?.users && searchResults.users.length > 0 ? (
                            <div className="p-1">
                              {searchResults.users.map((user) => (
                                <div
                                  key={user.id}
                                  onClick={() => {
                                    setInviteEmail(user.email)
                                    setEmailPopoverOpen(false)
                                    emailInputRef.current?.blur()
                                  }}
                                  className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 transition-colors hover:bg-[var(--surface-2)]"
                                >
                                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--surface-3)]">
                                    <Users className="h-4 w-4 text-[var(--text-secondary)]" />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <p className="truncate text-xs font-medium text-[var(--text-primary)]">
                                      {user.name || user.email}
                                    </p>
                                    {user.name && (
                                      <p className="truncate text-xs text-[var(--text-tertiary)]">
                                        {user.email}
                                      </p>
                                    )}
                                  </div>
                                  {inviteEmail === user.email && (
                                    <Check className="h-4 w-4 text-[var(--brand-600)]" />
                                  )}
                                </div>
                              ))}
                            </div>
                          ) : emailSearchQuery.length >= 2 ? (
                            <div className="px-3 py-6 text-center text-xs text-[var(--text-tertiary)]">
                              {t('workspace.noUsersFound')}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="mb-2 block text-xs font-medium text-[var(--text-secondary)]">
                      {t('workspace.role')}
                    </label>
                    <Select value={inviteRole} onValueChange={(v) => setInviteRole(v as any)}>
                      <SelectTrigger className="h-10 w-full border-[var(--border-strong)] transition-colors hover:border-[var(--border-strong)] focus:border-[var(--brand-500)] focus:ring-2 focus:ring-[var(--brand-500)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="min-w-[8rem] rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] py-1.5 shadow-xl [&_span[data-radix-select-item-indicator]]:left-2 [&_span[data-radix-select-item-indicator]]:flex [&_span[data-radix-select-item-indicator]]:h-5 [&_span[data-radix-select-item-indicator]]:w-5 [&_span[data-radix-select-item-indicator]]:items-center [&_span[data-radix-select-item-indicator]]:justify-center [&_span[data-radix-select-item-indicator]]:rounded-full [&_span[data-radix-select-item-indicator]]:bg-[var(--brand-50)] [&_span[data-radix-select-item-indicator]]:shadow-sm [&_svg]:h-3.5 [&_svg]:w-3.5 [&_svg]:stroke-[2.5] [&_svg]:text-[var(--brand-600)]">
                        {userPermissions.role === 'owner' && (
                          <SelectItem
                            value="admin"
                            className="mx-1 cursor-pointer rounded-md py-2.5 pl-10 pr-3 transition-colors hover:bg-[var(--brand-50)] focus:bg-[var(--brand-50)] active:bg-[var(--brand-100)]"
                          >
                            {t('workspace.roles.admin')}
                          </SelectItem>
                        )}
                        <SelectItem
                          value="member"
                          className="mx-1 cursor-pointer rounded-md py-2.5 pl-10 pr-3 transition-colors hover:bg-[var(--brand-50)] focus:bg-[var(--brand-50)] active:bg-[var(--brand-100)]"
                        >
                          {t('workspace.roles.member')}
                        </SelectItem>
                        <SelectItem
                          value="viewer"
                          className="mx-1 cursor-pointer rounded-md py-2.5 pl-10 pr-3 transition-colors hover:bg-[var(--brand-50)] focus:bg-[var(--brand-50)] active:bg-[var(--brand-100)]"
                        >
                          {t('workspace.roles.viewer')}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setInviteDialogOpen(false)}>
                    {t('workspace.cancel')}
                  </Button>
                  <Button onClick={handleInvite} disabled={addMemberMutation.isPending}>
                    {addMemberMutation.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {t('workspace.adding')}
                      </>
                    ) : (
                      <>
                        <UserPlus className="mr-2 h-4 w-4" />
                        {t('workspace.confirmAdd')}
                      </>
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      <div
        className="flex-1 overflow-y-auto p-6 transition-all duration-300"
        style={{
          marginLeft: isSidebarCollapsed ? '280px' : '0px',
        }}
      >
        {membersLoading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-[var(--text-muted)]" />
          </div>
        ) : members.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center text-center">
            <Users className="mb-4 h-16 w-16 text-[var(--text-subtle)]" />
            <h3 className="mb-2 text-base font-medium text-[var(--text-primary)]">{t('workspace.noMembers')}</h3>
            <p className="mb-4 text-xs text-[var(--text-tertiary)]">{t('workspace.noMembersDescription')}</p>
            {userPermissions.canAdmin && (
              <Button onClick={() => setInviteDialogOpen(true)}>
                <UserPlus className="mr-2 h-4 w-4" />
                {t('workspace.addMember')}
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg bg-[var(--surface-elevated)] shadow-sm">
              <Table>
                <TableHeader>
                  <TableRow className="border-none bg-[var(--surface-1)] hover:bg-[var(--surface-1)]">
                    <TableHead className="h-12 border-none text-xs font-semibold text-[var(--text-secondary)]">
                      {t('workspace.user')}
                    </TableHead>
                    <TableHead className="h-12 border-none text-xs font-semibold text-[var(--text-secondary)]">
                      {t('workspace.emailAddress')}
                    </TableHead>
                    <TableHead className="h-12 border-none text-xs font-semibold text-[var(--text-secondary)]">
                      {t('workspace.role')}
                    </TableHead>
                    <TableHead className="h-12 border-none text-xs font-semibold text-[var(--text-secondary)]">
                      {t('workspace.joinedAt')}
                    </TableHead>
                    <TableHead className="h-12 w-[140px] border-none text-right text-xs font-semibold text-[var(--text-secondary)]">
                      {t('workspace.actions')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => {
                    const RoleIcon = ROLE_ICONS[member.role]
                    const currentRole = userPermissions.role
                    const canModify = (() => {
                      if (member.isOwner) return false
                      if (currentRole === 'owner') return true
                      if (
                        currentRole === 'admin' &&
                        (member.role === 'member' || member.role === 'viewer')
                      )
                        return true
                      return false
                    })()
                    const initials = (member.name || member.email)
                      .split(' ')
                      .map((n) => n[0])
                      .join('')
                      .toUpperCase()
                      .slice(0, 2)
                    const joinedDate = member.createdAt
                      ? formatDate(new Date(member.createdAt), 'yyyy-MM-dd')
                      : '-'

                    return (
                      <TableRow
                        key={member.id}
                        className="border-none transition-colors hover:bg-[var(--surface-1)]"
                      >
                        <TableCell className="border-0 py-4">
                          <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-600)] text-xs font-semibold text-white shadow-sm">
                              {initials}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <p className="truncate text-xs font-semibold text-[var(--text-primary)]">
                                  {member.name || '-'}
                                </p>
                                {member.isOwner && (
                                  <Badge
                                    variant="secondary"
                                    className="border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] px-2 py-0.5 text-[var(--status-warning)]"
                                  >
                                    <Crown className="mr-1 h-3 w-3" />
                                    {t('workspace.roles.owner')}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="border-0 py-4">
                          <p className="text-xs text-[var(--text-secondary)]">{member.email}</p>
                        </TableCell>
                        <TableCell className="border-0 py-4">
                          {updateMemberId === member.userId ? (
                            <div className="flex flex-wrap items-center gap-2">
                              <Select
                                value={updateRole || member.role}
                                onValueChange={(v) => setUpdateRole(v as any)}
                              >
                                <SelectTrigger className="h-9 w-36 border-[var(--border-strong)]">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {userPermissions.role === 'owner' && (
                                    <SelectItem value="admin">
                                      {t('workspace.roles.admin')}
                                    </SelectItem>
                                  )}
                                  <SelectItem value="member">
                                    {t('workspace.roles.member')}
                                  </SelectItem>
                                  <SelectItem value="viewer">
                                    {t('workspace.roles.viewer')}
                                  </SelectItem>
                                </SelectContent>
                              </Select>
                              <Button
                                size="sm"
                                className="h-9"
                                onClick={() => {
                                  if (updateRole && updateRole !== member.role) {
                                    handleUpdateRole(member.userId, updateRole)
                                  } else {
                                    setUpdateMemberId(null)
                                    setUpdateRole(null)
                                  }
                                }}
                                disabled={updateRoleMutation.isPending}
                              >
                                {updateRoleMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  t('workspace.save')
                                )}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-9"
                                onClick={() => {
                                  setUpdateMemberId(null)
                                  setUpdateRole(null)
                                }}
                              >
                                {t('workspace.cancel')}
                              </Button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--surface-3)]">
                                <RoleIcon className="h-4 w-4 text-[var(--text-secondary)]" />
                              </div>
                              <span className="text-xs font-medium text-[var(--text-secondary)]">
                                {t(`workspace.roles.${member.role}`)}
                              </span>
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="border-0 py-4">
                          <p className="text-xs text-[var(--text-secondary)]">{joinedDate}</p>
                        </TableCell>
                        <TableCell className="border-0 py-4 text-right">
                          {canModify && updateMemberId !== member.userId ? (
                            <TooltipProvider>
                              <div className="flex items-center justify-end gap-1">
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-8 w-8 p-0 hover:bg-[var(--brand-50)] hover:text-[var(--brand-600)]"
                                      onClick={() => {
                                        setUpdateMemberId(member.userId)
                                        setUpdateRole(member.role as any)
                                      }}
                                    >
                                      <Edit className="h-4 w-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>{t('workspace.updateRole')}</p>
                                  </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-8 w-8 p-0 hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error)]"
                                      onClick={() => setRemoveMemberId(member.userId)}
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>{t('workspace.removeMember')}</p>
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                            </TooltipProvider>
                          ) : (
                            <span className="text-xs text-[var(--text-muted)]">-</span>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>

            {!membersLoading && totalMembers > 0 && (
              <div className="mt-4 px-1">
                <Pagination
                  page={page}
                  totalPages={totalPages}
                  total={totalMembers}
                  pageSize={pageSize}
                  isLoading={membersLoading}
                  onPageChange={setPage}
                />
              </div>
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!removeMemberId}
        onOpenChange={(open) => !open && setRemoveMemberId(null)}
        title={t('workspace.confirmRemoveMember')}
        description={t('workspace.confirmRemoveMemberDescription')}
        confirmLabel={t('workspace.confirmRemove')}
        cancelLabel={t('workspace.cancel')}
        variant="destructive"
        onConfirm={() => {
          if (removeMemberId) {
            handleRemoveMember(removeMemberId)
          }
        }}
        onCancel={() => setRemoveMemberId(null)}
      />
    </div>
  )
}
