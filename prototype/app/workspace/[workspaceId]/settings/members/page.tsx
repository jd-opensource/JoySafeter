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
import { Users, UserPlus, Mail, Shield, Crown, Eye, Edit, Trash2, Loader2, Check } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState, useEffect, useRef } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
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
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { workspaceService, type WorkspaceMember, type PaginatedMembersResponse } from '@/services/workspaceService'
import { useToast } from '@/hooks/use-toast'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
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

  const { permissions, loading: permissionsLoading, refetch } = useWorkspacePermissions(
    workspaceId,
    { useFullList: true } // 明确需要完整列表
  )
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

  // Get sidebar state to adjust layout
  const isSidebarCollapsed = useSidebarStore((state) => state.isCollapsed)
  const sidebarWidth = useSidebarStore((state) => state.sidebarWidth)

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

  const { data: searchResults, isLoading: isSearching } = useQuery<{ users: Array<{ id: string; email: string; name: string | null; image: string | null }> }>({
    queryKey: ['search-users', workspaceId, emailSearchQuery],
    queryFn: () => workspaceService.searchUsers(workspaceId, emailSearchQuery, 10),
    enabled: !!workspaceId && !!emailSearchQuery && emailSearchQuery.length >= 2 && userPermissions.canAdmin,
    staleTime: 5000,
  })

  useEffect(() => {
    const timer = setTimeout(() => {
      setEmailSearchQuery(inviteEmail)
    }, 300)

    return () => clearTimeout(timer)
  }, [inviteEmail])

  const inviteMutation = useMutation({
    mutationFn: async ({ email, role }: { email: string; role: string }) => {
      return workspaceService.sendInvitation({
        workspaceId,
        email,
        role,
      })
    },
    onSuccess: () => {
      toastSuccess(
        t('workspace.inviteSentDescription', { email: inviteEmail }),
        t('workspace.inviteSent')
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
        errorMessage.includes('already a member') ||
        errorMessage.includes('is already a member')

      if (isAlreadyMember) {
        toastError(
          t('workspace.userAlreadyMemberDescription', { email: inviteEmail }),
          t('workspace.userAlreadyMember')
        )
      } else {
        toastError(
          rawMessage || t('workspace.inviteFailed'),
          t('workspace.inviteFailed')
        )
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
    onError: (error: Error) => {
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
    onError: (error: Error) => {
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
    inviteMutation.mutate({ email: inviteEmail.trim(), role: inviteRole })
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

  if (!userPermissions.canRead) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Shield className="mx-auto h-12 w-12 text-gray-400 mb-4" />
          <h2 className="text-base font-semibold text-gray-900 mb-2">{t('workspace.noAccess')}</h2>
          <p className="text-xs text-gray-500">{t('workspace.noAccessDescription')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex-shrink-0 border-b border-gray-200 bg-white py-4 px-6 transition-all duration-300"
        style={{
          marginLeft: isSidebarCollapsed ? '280px' : '0px',
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Users className="h-6 w-6 text-gray-700" />
            <h1 className="text-base font-semibold text-gray-900">{t('workspace.membersManagement')}</h1>
          </div>
          {userPermissions.canAdmin && (
            <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
              <DialogTrigger asChild>
                <Button>
                  <UserPlus className="h-4 w-4 mr-2" />
                  {t('workspace.inviteMember')}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t('workspace.inviteNewMember')}</DialogTitle>
                  <DialogDescription>{t('workspace.inviteMemberDescription')}</DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div>
                    <label className="text-xs font-medium text-gray-700 mb-2 block">{t('workspace.emailAddress')}</label>
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
                          className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-auto"
                          onMouseDown={(e) => {
                            e.preventDefault()
                          }}
                        >
                          {isSearching ? (
                            <div className="flex items-center justify-center py-6">
                              <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
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
                                  className="flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer hover:bg-gray-50 transition-colors"
                                >
                                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100">
                                    <Users className="h-4 w-4 text-gray-600" />
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <p className="text-xs font-medium text-gray-900 truncate">
                                      {user.name || user.email}
                                    </p>
                                    {user.name && (
                                      <p className="text-[10px] text-gray-500 truncate">{user.email}</p>
                                    )}
                                  </div>
                                  {inviteEmail === user.email && (
                                    <Check className="h-4 w-4 text-blue-600" />
                                  )}
                                </div>
                              ))}
                            </div>
                          ) : emailSearchQuery.length >= 2 ? (
                            <div className="px-3 py-6 text-center text-xs text-gray-500">
                              {t('workspace.noUsersFound')}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-700 mb-2 block">{t('workspace.role')}</label>
                    <Select value={inviteRole} onValueChange={(v) => setInviteRole(v as any)}>
                      <SelectTrigger className="h-10 w-full border-gray-300 hover:border-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="z-[10000001] rounded-lg border border-gray-200 shadow-xl bg-white py-1.5 min-w-[8rem] [&_span[data-radix-select-item-indicator]]:bg-blue-50 [&_span[data-radix-select-item-indicator]]:rounded-full [&_span[data-radix-select-item-indicator]]:w-5 [&_span[data-radix-select-item-indicator]]:h-5 [&_span[data-radix-select-item-indicator]]:flex [&_span[data-radix-select-item-indicator]]:items-center [&_span[data-radix-select-item-indicator]]:justify-center [&_span[data-radix-select-item-indicator]]:shadow-sm [&_span[data-radix-select-item-indicator]]:left-2 [&_svg]:text-blue-600 [&_svg]:w-3.5 [&_svg]:h-3.5 [&_svg]:stroke-[2.5]">
                        <SelectItem
                          value="admin"
                          className="cursor-pointer hover:bg-blue-50 active:bg-blue-100 py-2.5 pl-10 pr-3 rounded-md mx-1 transition-colors focus:bg-blue-50"
                        >
                          {t('workspace.roles.admin')}
                        </SelectItem>
                        <SelectItem
                          value="member"
                          className="cursor-pointer hover:bg-blue-50 active:bg-blue-100 py-2.5 pl-10 pr-3 rounded-md mx-1 transition-colors focus:bg-blue-50"
                        >
                          {t('workspace.roles.member')}
                        </SelectItem>
                        <SelectItem
                          value="viewer"
                          className="cursor-pointer hover:bg-blue-50 active:bg-blue-100 py-2.5 pl-10 pr-3 rounded-md mx-1 transition-colors focus:bg-blue-50"
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
                  <Button onClick={handleInvite} disabled={inviteMutation.isPending}>
                    {inviteMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        {t('workspace.sending')}
                      </>
                    ) : (
                      <>
                        <Mail className="h-4 w-4 mr-2" />
                        {t('workspace.sendInvitation')}
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
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
          </div>
        ) : members.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <Users className="h-16 w-16 text-gray-300 mb-4" />
            <h3 className="text-base font-medium text-gray-900 mb-2">{t('workspace.noMembers')}</h3>
            <p className="text-xs text-gray-500 mb-4">{t('workspace.noMembersDescription')}</p>
            {userPermissions.canAdmin && (
              <Button onClick={() => setInviteDialogOpen(true)}>
                <UserPlus className="h-4 w-4 mr-2" />
                {t('workspace.inviteMember')}
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg bg-white shadow-sm">
              <Table>
                <TableHeader>
                  <TableRow className="bg-gray-50/50 hover:bg-gray-50/50 border-none">
                    <TableHead className="h-12 text-xs font-semibold text-gray-700 border-none">{t('workspace.user')}</TableHead>
                    <TableHead className="h-12 text-xs font-semibold text-gray-700 border-none">{t('workspace.emailAddress')}</TableHead>
                    <TableHead className="h-12 text-xs font-semibold text-gray-700 border-none">{t('workspace.role')}</TableHead>
                    <TableHead className="h-12 text-xs font-semibold text-gray-700 border-none">{t('workspace.joinedAt')}</TableHead>
                    <TableHead className="text-right w-[140px] h-12 text-xs font-semibold text-gray-700 border-none">{t('workspace.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => {
                    const RoleIcon = ROLE_ICONS[member.role]
                    const canModify = userPermissions.canAdmin && !member.isOwner
                    const initials = (member.name || member.email)
                      .split(' ')
                      .map(n => n[0])
                      .join('')
                      .toUpperCase()
                      .slice(0, 2)
                    const joinedDate = member.createdAt ? formatDate(new Date(member.createdAt), 'yyyy-MM-dd') : '-'

                    return (
                      <TableRow key={member.id} className="hover:bg-gray-50/50 transition-colors border-none">
                        <TableCell className="py-4 border-0">
                          <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-600 text-white text-xs font-semibold shadow-sm">
                              {initials}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-xs font-semibold text-gray-900 truncate">
                                  {member.name || '-'}
                                </p>
                                {member.isOwner && (
                                  <Badge variant="secondary" className="bg-yellow-100 text-yellow-800 border-yellow-200 px-2 py-0.5">
                                    <Crown className="h-3 w-3 mr-1" />
                                    {t('workspace.roles.owner')}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="py-4 border-0">
                          <p className="text-xs text-gray-700">{member.email}</p>
                        </TableCell>
                        <TableCell className="py-4 border-0">
                          {updateMemberId === member.userId ? (
                            <div className="flex items-center gap-2 flex-wrap">
                              <Select
                                value={updateRole || member.role}
                                onValueChange={(v) => setUpdateRole(v as any)}
                              >
                                <SelectTrigger className="w-36 h-9 border-gray-300">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="admin">
                                    {t('workspace.roles.admin')}
                                  </SelectItem>
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
                              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-gray-100">
                                <RoleIcon className="h-4 w-4 text-gray-600" />
                              </div>
                              <span className="text-xs font-medium text-gray-700">
                                {t(`workspace.roles.${member.role}`)}
                              </span>
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="py-4 border-0">
                          <p className="text-xs text-gray-600">{joinedDate}</p>
                        </TableCell>
                        <TableCell className="text-right py-4 border-0">
                          {canModify && updateMemberId !== member.userId ? (
                            <TooltipProvider>
                              <div className="flex items-center justify-end gap-1">
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-8 w-8 p-0 hover:bg-blue-50 hover:text-blue-600"
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
                                      className="h-8 w-8 p-0 hover:bg-red-50 hover:text-red-600"
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
                            <span className="text-xs text-gray-400">-</span>
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

      <AlertDialog open={!!removeMemberId} onOpenChange={(open) => !open && setRemoveMemberId(null)}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.confirmRemoveMember')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('workspace.confirmRemoveMemberDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setRemoveMemberId(null)}>{t('workspace.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removeMemberId) {
                  handleRemoveMember(removeMemberId)
                }
              }}
              className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
            >
              {t('workspace.confirmRemove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
