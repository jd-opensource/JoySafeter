'use client'

import { useState, useRef, useEffect, type MutableRefObject } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedPut, managedDelete } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { UserPlus, Trash2, Search } from 'lucide-react'
import { DataTable, RelativeTime, type Column, PageHeader } from '@/components/managed/shared'
import { toastOperationError } from '@/lib/managed/errors'
import { useSession } from '@/lib/auth/auth-client'
import { normalizeManagedRole, roleLabel, roleOptions } from '@/lib/managed/roles'
import { useUserPermissionsContext } from '@/providers/permissions-provider'
import { useProjectStore } from '@/stores/managed/project-store'

interface MemberRecord {
  user_id: string
  email: string
  display_name: string
  role: string
  joined_at?: string
}

export default function MembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const session = useSession()
  const { canAdmin } = useUserPermissionsContext()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const orgScope = currentOrgId ?? ''
  const orgScopeRef = useRef(orgScope)
  const previousOrgScopeRef = useRef<string | null>(null)
  const inviteRunRef = useRef(0)
  const roleRunRef = useRef(0)
  const removeRunRef = useRef(0)

  // ── State ──
  const [showInvite, setShowInvite] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('developer')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<
    { id: string; email: string; name: string; image?: string; already_member: boolean }[]
  >([])
  const [showDropdown, setShowDropdown] = useState(false)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchRequestSeqRef = useRef(0)

  // Role change dialog
  const [roleTarget, setRoleTarget] = useState<MemberRecord | null>(null)
  const [newRole, setNewRole] = useState('developer')

  // Remove confirm
  const [removeTarget, setRemoveTarget] = useState<MemberRecord | null>(null)

  // ── Queries ──
  const { data: members = [], isLoading } = useQuery({
    queryKey: ['org-members', currentOrgId],
    queryFn: () => managedGet<MemberRecord[]>('auth/members'),
  })

  const getCurrentOrgScope = () => useProjectStore.getState().currentOrgId ?? ''

  const currentOrgScopeIsActive = (scope = orgScopeRef.current) =>
    orgScopeRef.current === scope && getCurrentOrgScope() === scope

  const isCurrentScopedRun = (runRef: MutableRefObject<number>, runId: number, scope: string) =>
    runRef.current === runId && currentOrgScopeIsActive(scope)

  const currentMutableMember = (member: MemberRecord | null) => {
    if (!member) return null
    if (!currentOrgScopeIsActive()) return null
    const current = queryClient
      .getQueryData<MemberRecord[]>(['org-members', orgScopeRef.current])
      ?.find((candidate) => candidate.user_id === member.user_id)
    return current && normalizeManagedRole(current.role) !== 'owner' ? current : null
  }

  useEffect(() => {
    return () => {
      inviteRunRef.current += 1
      roleRunRef.current += 1
      removeRunRef.current += 1
      searchRequestSeqRef.current += 1
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current)
        searchTimeoutRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (previousOrgScopeRef.current === null) {
      previousOrgScopeRef.current = orgScope
      orgScopeRef.current = orgScope
      return
    }
    if (previousOrgScopeRef.current === orgScope) return
    previousOrgScopeRef.current = orgScope
    orgScopeRef.current = orgScope
    inviteRunRef.current += 1
    roleRunRef.current += 1
    removeRunRef.current += 1
    searchRequestSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setShowInvite(false)
    setEmail('')
    setRole('developer')
    setSearchQuery('')
    setSearchResults([])
    setShowDropdown(false)
    setRoleTarget(null)
    setNewRole('developer')
    setRemoveTarget(null)
  }, [orgScope])

  useEffect(() => {
    const currentById = new Map(members.map((member) => [member.user_id, member]))
    setRoleTarget((target) => {
      if (!target) return null
      const current = currentById.get(target.user_id)
      if (!current || normalizeManagedRole(current.role) === 'owner') {
        roleRunRef.current += 1
        return null
      }
      return current
    })
    setRemoveTarget((target) => {
      if (!target) return null
      const current = currentById.get(target.user_id)
      if (!current || normalizeManagedRole(current.role) === 'owner') {
        removeRunRef.current += 1
        return null
      }
      return current
    })
  }, [members])

  // ── Mutations ──
  const inviteMember = useMutation({
    mutationFn: (data: { email: string; role: string; runId: number; scope: string }) => {
      if (!currentOrgScopeIsActive(data.scope) || data.runId !== inviteRunRef.current) {
        throw new Error('Stale member invite ignored')
      }
      return managedPost<MemberRecord>('auth/members/invite', {
        email: data.email,
        role: data.role,
      }).then((member) => ({ member, runId: data.runId, scope: data.scope }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(inviteRunRef, runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['org-members', scope] })
      resetInviteDialog(false)
    },
    onError: (err: Error, variables) => {
      if (!isCurrentScopedRun(inviteRunRef, variables.runId, variables.scope)) return
      toastOperationError(t, err, 'manage.members.inviteFailed')
    },
  })

  const removeMemberMut = useMutation({
    mutationFn: ({ userId, runId, scope }: { userId: string; runId: number; scope: string }) => {
      if (!currentOrgScopeIsActive(scope) || runId !== removeRunRef.current) {
        throw new Error('Stale member removal ignored')
      }
      return managedDelete(`auth/members/${userId}`).then(() => ({ runId, scope }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(removeRunRef, runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['org-members', scope] })
      setRemoveTarget(null)
    },
    onError: (err: Error, variables) => {
      if (!isCurrentScopedRun(removeRunRef, variables.runId, variables.scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  const updateRoleMut = useMutation({
    mutationFn: ({
      userId,
      role,
      runId,
      scope,
    }: {
      userId: string
      role: string
      runId: number
      scope: string
    }) => {
      if (!currentOrgScopeIsActive(scope) || runId !== roleRunRef.current) {
        throw new Error('Stale member role update ignored')
      }
      return managedPut<MemberRecord>(`auth/members/${userId}`, { role }).then((member) => ({
        member,
        runId,
        scope,
      }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(roleRunRef, runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['org-members', scope] })
      setRoleTarget(null)
    },
    onError: (err: Error, variables) => {
      if (!isCurrentScopedRun(roleRunRef, variables.runId, variables.scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  // ── Handlers ──
  const resetInviteDialog = (open: boolean) => {
    inviteRunRef.current += 1
    setShowInvite(open)
    if (!open) {
      searchRequestSeqRef.current += 1
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current)
        searchTimeoutRef.current = null
      }
      setEmail('')
      setRole('developer')
      setSearchQuery('')
      setSearchResults([])
      setShowDropdown(false)
    }
  }

  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    setEmail(value)
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    const requestSeq = (searchRequestSeqRef.current += 1)
    if (value.length < 2) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    const requestScope = orgScopeRef.current
    searchTimeoutRef.current = setTimeout(async () => {
      if (!currentOrgScopeIsActive(requestScope)) return
      try {
        const results = await managedGet<
          { id: string; email: string; name: string; image?: string; already_member: boolean }[]
        >(`/auth/search-users?q=${encodeURIComponent(value)}&limit=5`)
        if (requestSeq !== searchRequestSeqRef.current || !currentOrgScopeIsActive(requestScope))
          return
        setSearchResults(results)
        setShowDropdown(true)
      } catch {
        if (requestSeq !== searchRequestSeqRef.current || !currentOrgScopeIsActive(requestScope))
          return
        setSearchResults([])
      }
    }, 300)
  }

  const selectUser = (user: { id: string; email: string; name: string }) => {
    searchRequestSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setEmail(user.email)
    setSearchQuery(user.email)
    setShowDropdown(false)
  }

  const handleInvite = () => {
    const trimmedEmail = email.trim()
    if (!trimmedEmail) return
    if (!currentOrgScopeIsActive()) return
    const emailAlreadyMember = queryClient
      .getQueryData<MemberRecord[]>(['org-members', orgScopeRef.current])
      ?.some((member) => member.email.toLowerCase() === trimmedEmail.toLowerCase())
    if (emailAlreadyMember) return
    const runId = inviteRunRef.current + 1
    inviteRunRef.current = runId
    inviteMember.mutate({ email: trimmedEmail, role, runId, scope: orgScopeRef.current })
  }

  const openRoleDialog = (m: MemberRecord) => {
    if (!currentOrgScopeIsActive()) return
    const current = currentMutableMember(m)
    if (!current) return

    roleRunRef.current += 1
    setRoleTarget(current)
    setNewRole(current.role)
  }

  const closeRoleDialog = () => {
    roleRunRef.current += 1
    setRoleTarget(null)
  }

  const openRemoveDialog = (m: MemberRecord) => {
    if (!currentOrgScopeIsActive()) return
    const current = currentMutableMember(m)
    if (!current) return

    removeRunRef.current += 1
    setRemoveTarget(current)
  }

  const closeRemoveDialog = () => {
    removeRunRef.current += 1
    setRemoveTarget(null)
  }

  const handleChangeRole = () => {
    if (!currentOrgScopeIsActive()) return
    const target = currentMutableMember(roleTarget)
    if (!target) {
      closeRoleDialog()
      return
    }
    const runId = roleRunRef.current + 1
    roleRunRef.current = runId
    updateRoleMut.mutate({
      userId: target.user_id,
      role: newRole,
      runId,
      scope: orgScopeRef.current,
    })
  }

  const handleRemove = () => {
    if (!currentOrgScopeIsActive()) return
    const target = currentMutableMember(removeTarget)
    if (!target) {
      closeRemoveDialog()
      return
    }
    const runId = removeRunRef.current + 1
    removeRunRef.current = runId
    removeMemberMut.mutate({
      userId: target.user_id,
      runId,
      scope: orgScopeRef.current,
    })
  }

  const columns: Column<MemberRecord>[] = [
    {
      key: 'name',
      header: t('manage.members.name'),
      render: (member) => (
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
            {member.display_name?.charAt(0)?.toUpperCase() || '?'}
          </div>
          <span className="font-medium text-foreground">
            {member.display_name || '-'}
            {member.user_id === session?.data?.user?.id && (
              <span className="ml-1.5 text-xs text-muted-foreground">
                ({t('manage.members.you')})
              </span>
            )}
          </span>
        </div>
      ),
    },
    {
      key: 'email',
      header: t('manage.members.email'),
      render: (member) => <span className="text-muted-foreground">{member.email}</span>,
    },
    {
      key: 'role',
      header: t('manage.members.role'),
      render: (member) => (
        <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium">
          {roleLabel(t, member.role)}
        </span>
      ),
    },
    {
      key: 'joined',
      header: t('manage.members.joined'),
      render: (member) =>
        member.joined_at ? (
          <RelativeTime date={member.joined_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.members.title')}
        subtitle={t('manage.members.subtitle')}
        action={
          canAdmin ? (
            <Button size="sm" onClick={() => resetInviteDialog(true)}>
              <UserPlus className="mr-1 h-4 w-4" />
              {t('manage.members.invite')}
            </Button>
          ) : null
        }
      />

      <DataTable
        columns={columns}
        data={members}
        loading={isLoading}
        emptyMessage={t('manage.members.empty')}
        actionMenu={
          canAdmin
            ? (member) =>
                normalizeManagedRole(member.role) === 'owner'
                  ? []
                  : [
                      {
                        label: t('manage.members.changeRole'),
                        onClick: () => openRoleDialog(member),
                      },
                      {
                        label: t('manage.members.remove'),
                        icon: <Trash2 className="h-3.5 w-3.5" />,
                        destructive: true,
                        onClick: () => openRemoveDialog(member),
                      },
                    ]
            : undefined
        }
      />

      {/* Invite Dialog */}
      <Dialog open={showInvite} onOpenChange={resetInviteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.invite')}</DialogTitle>
            <DialogDescription>{t('manage.members.subtitle')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.email')}</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="user@example.com"
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  className="pl-9"
                  autoFocus
                />
                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-lg border border-border bg-background shadow-lg">
                    {searchResults.map((user) => (
                      <button
                        key={user.id}
                        type="button"
                        disabled={user.already_member}
                        onClick={() => selectUser(user)}
                        className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                          {user.name?.charAt(0)?.toUpperCase() ||
                            user.email?.charAt(0)?.toUpperCase() ||
                            '?'}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-foreground">
                            {user.name || user.email}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">{user.email}</div>
                        </div>
                        {user.already_member && (
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {t('manage.members.alreadyMember')}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.role')}</label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleOptions(t).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => resetInviteDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleInvite} disabled={!email.trim() || inviteMember.isPending}>
              {inviteMember.isPending ? t('common.loading') : t('manage.members.invite')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Change Role Dialog */}
      <Dialog
        open={!!roleTarget}
        onOpenChange={(v) => {
          if (!v) closeRoleDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.changeRole')}</DialogTitle>
            <DialogDescription>{roleTarget?.display_name || roleTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Select value={newRole} onValueChange={setNewRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roleOptions(t).map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeRoleDialog}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleChangeRole} disabled={newRole === roleTarget?.role}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Confirm Dialog */}
      <Dialog
        open={!!removeTarget}
        onOpenChange={(v) => {
          if (!v) closeRemoveDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.remove')}</DialogTitle>
            <DialogDescription>{t('manage.members.removeConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={closeRemoveDialog}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleRemove}>
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
