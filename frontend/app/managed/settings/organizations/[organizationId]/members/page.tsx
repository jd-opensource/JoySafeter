'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, Search, Settings2, Trash2, UserPlus } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState, useRef, useEffect, type MutableRefObject } from 'react'

import {
  DataTable,
  FilterBar,
  RelativeTime,
  type Column,
  type FilterDef,
  PageHeader,
} from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedGet, managedPost, managedPut, managedDelete } from '@/lib/api-client'
import { useSession } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  DEFAULT_ORGANIZATION_ROLE,
  normalizeManagedRole,
  roleLabel,
  roleOptions,
} from '@/lib/managed/roles'
import {
  parseMemberCandidateListResponse,
  parseOrganizationDetailResponse,
  parseOrganizationMemberResponse,
  type MemberCandidate,
  type OrganizationMemberRecord,
} from '@/lib/managed/tenant-response-parsers'
import {
  parseOrganizationId,
  parseOrganizationMemberId,
  type OrganizationId,
  type UserId,
} from '@/types/entity-id'

export default function MembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const session = useSession()
  const params = useParams<{ organizationId: string }>()
  const organizationId = parseOrganizationId(params.organizationId)
  const organizationQuery = useQuery({
    queryKey: ['organization-detail', organizationId],
    queryFn: () =>
      managedGet<unknown>(`organizations/${organizationId}`).then(parseOrganizationDetailResponse),
    enabled: Boolean(organizationId),
  })
  const currentOrganization = organizationQuery.data
  const canManage = ['owner', 'admin'].includes(normalizeManagedRole(currentOrganization?.role))
  const orgScope = organizationId
  const orgScopeRef = useRef(orgScope)
  const previousOrgScopeRef = useRef<OrganizationId | null>(null)
  const addMemberRunRef = useRef(0)
  const roleRunRef = useRef(0)
  const removeRunRef = useRef(0)

  // ── State ──
  const [showAddMember, setShowAddMember] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<string>(DEFAULT_ORGANIZATION_ROLE)
  const [memberSearch, setMemberSearch] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<MemberCandidate[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchRequestSeqRef = useRef(0)

  // Role change dialog
  const [roleTarget, setRoleTarget] = useState<OrganizationMemberRecord | null>(null)
  const [newRole, setNewRole] = useState<string>(DEFAULT_ORGANIZATION_ROLE)

  // Remove confirm
  const [removeTarget, setRemoveTarget] = useState<OrganizationMemberRecord | null>(null)

  // ── Queries ──
  const {
    data: members,
    isLoading,
    isFetching,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset: resetMembersPagination,
  } = usePaginatedList<OrganizationMemberRecord>({
    queryKey: 'organization-members',
    path: `/organizations/${organizationId}/members${memberSearch.trim() ? `?q=${encodeURIComponent(memberSearch.trim())}` : ''}`,
    enabled: Boolean(organizationId),
    parseItem: parseOrganizationMemberResponse,
    parseCursor: parseOrganizationMemberId,
  })
  const filteredMembers = members.filter(
    (member) =>
      filterByCreatedTime(member.joined_at || '', createdFilter) &&
      matchesSearch(memberSearch, [member.user_id, member.user_name, member.user_email]),
  )
  const normalizedMemberEmail = email.trim().toLowerCase()
  const emailAlreadyMember =
    !!normalizedMemberEmail &&
    (members.some((member) => (member.user_email ?? '').toLowerCase() === normalizedMemberEmail) ||
      searchResults.some(
        (user) => user.email.toLowerCase() === normalizedMemberEmail && user.already_member,
      ))

  const currentOrgScopeIsActive = (scope = orgScopeRef.current) =>
    orgScopeRef.current === scope && organizationId === scope

  const isCurrentScopedRun = (
    runRef: MutableRefObject<number>,
    runId: number,
    scope: OrganizationId,
  ) => runRef.current === runId && currentOrgScopeIsActive(scope)

  const currentMutableMember = (member: OrganizationMemberRecord | null) => {
    if (!member) return null
    if (!currentOrgScopeIsActive()) return null
    const current = members.find((candidate) => candidate.user_id === member.user_id)
    return current && normalizeManagedRole(current.role) !== 'owner' ? current : null
  }

  useEffect(() => {
    return () => {
      addMemberRunRef.current += 1
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
    addMemberRunRef.current += 1
    roleRunRef.current += 1
    removeRunRef.current += 1
    searchRequestSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setShowAddMember(false)
    setEmail('')
    setRole(DEFAULT_ORGANIZATION_ROLE)
    setMemberSearch('')
    setCreatedFilter('all')
    setSearchQuery('')
    setSearchResults([])
    setShowDropdown(false)
    setRoleTarget(null)
    setNewRole(DEFAULT_ORGANIZATION_ROLE)
    setRemoveTarget(null)
    resetMembersPagination()
  }, [orgScope, resetMembersPagination])

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
  const addMemberMutation = useMutation({
    mutationFn: (data: { email: string; role: string; runId: number; scope: OrganizationId }) => {
      if (!currentOrgScopeIsActive(data.scope) || data.runId !== addMemberRunRef.current) {
        throw new Error('Stale member addition ignored')
      }
      return managedPost<unknown>(`organizations/${data.scope}/members`, {
        email: data.email,
        role: data.role,
      })
        .then(parseOrganizationMemberResponse)
        .then((member) => ({ member, runId: data.runId, scope: data.scope }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(addMemberRunRef, runId, scope)) return
      resetMembersPagination()
      queryClient.invalidateQueries({ queryKey: ['organization-members'] })
      queryClient.invalidateQueries({ queryKey: ['organization-members', scope] })
      resetAddMemberDialog(false)
    },
    onError: (err: Error, variables) => {
      if (!isCurrentScopedRun(addMemberRunRef, variables.runId, variables.scope)) return
      toastOperationError(t, err, 'manage.members.addFailed')
    },
  })

  const removeMemberMut = useMutation({
    mutationFn: ({
      userId,
      runId,
      scope,
    }: {
      userId: UserId
      runId: number
      scope: OrganizationId
    }) => {
      if (!currentOrgScopeIsActive(scope) || runId !== removeRunRef.current) {
        throw new Error('Stale member removal ignored')
      }
      return managedDelete(`organizations/${scope}/members/${userId}`).then(() => ({
        runId,
        scope,
      }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(removeRunRef, runId, scope)) return
      resetMembersPagination()
      queryClient.invalidateQueries({ queryKey: ['organization-members'] })
      queryClient.invalidateQueries({ queryKey: ['organization-members', scope] })
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
      userId: UserId
      role: string
      runId: number
      scope: OrganizationId
    }) => {
      if (!currentOrgScopeIsActive(scope) || runId !== roleRunRef.current) {
        throw new Error('Stale member role update ignored')
      }
      return managedPut<unknown>(`organizations/${scope}/members/${userId}`, { role })
        .then(parseOrganizationMemberResponse)
        .then((member) => ({
          member,
          runId,
          scope,
        }))
    },
    onSuccess: ({ runId, scope }) => {
      if (!isCurrentScopedRun(roleRunRef, runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['organization-members'] })
      queryClient.invalidateQueries({ queryKey: ['organization-members', scope] })
      setRoleTarget(null)
    },
    onError: (err: Error, variables) => {
      if (!isCurrentScopedRun(roleRunRef, variables.runId, variables.scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  // ── Handlers ──
  const resetAddMemberDialog = (open: boolean) => {
    addMemberRunRef.current += 1
    setShowAddMember(open)
    if (!open) {
      searchRequestSeqRef.current += 1
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current)
        searchTimeoutRef.current = null
      }
      setEmail('')
      setRole(DEFAULT_ORGANIZATION_ROLE)
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
        const results = await managedGet<unknown>(
          `organizations/${requestScope}/member-candidates?q=${encodeURIComponent(value)}&limit=5`,
        ).then(parseMemberCandidateListResponse)
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

  const selectUser = (user: MemberCandidate) => {
    searchRequestSeqRef.current += 1
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
      searchTimeoutRef.current = null
    }
    setEmail(user.email)
    setSearchQuery(user.email)
    setShowDropdown(false)
  }

  const handleAddMember = () => {
    const trimmedEmail = email.trim()
    if (!trimmedEmail || emailAlreadyMember) return
    if (!currentOrgScopeIsActive()) return
    const runId = addMemberRunRef.current + 1
    addMemberRunRef.current = runId
    addMemberMutation.mutate({ email: trimmedEmail, role, runId, scope: orgScopeRef.current })
  }

  const openRoleDialog = (m: OrganizationMemberRecord) => {
    if (!currentOrgScopeIsActive()) return
    const current = currentMutableMember(m)
    if (!current) return

    roleRunRef.current += 1
    setRoleTarget(current)
    setNewRole(normalizeManagedRole(current.role))
  }

  const closeRoleDialog = () => {
    roleRunRef.current += 1
    setRoleTarget(null)
  }

  const openRemoveDialog = (m: OrganizationMemberRecord) => {
    if (!currentOrgScopeIsActive()) return
    const current = currentMutableMember(m)
    if (!current) return

    removeRunRef.current += 1
    setRemoveTarget(current)
  }

  const openRemoveFromRoleDialog = () => {
    const target = currentMutableMember(roleTarget)
    if (!target) {
      closeRoleDialog()
      return
    }
    roleRunRef.current += 1
    setRoleTarget(null)
    openRemoveDialog(target)
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

  const renderMemberManageAction = (member: OrganizationMemberRecord, fullWidth = false) => {
    if (!canManage) return null
    if (normalizeManagedRole(member.role) === 'owner') {
      return (
        <span className="text-xs text-muted-foreground">{t('manage.members.ownerProtected')}</span>
      )
    }
    if (member.user_id === session?.data?.user?.id) {
      return (
        <span className="text-xs text-muted-foreground">
          {t('manage.members.currentAccountProtected')}
        </span>
      )
    }
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={fullWidth ? 'w-full' : undefined}
        onClick={() => openRoleDialog(member)}
      >
        <Settings2 className="h-3.5 w-3.5" />
        {t('manage.members.manage')}
      </Button>
    )
  }

  const columns: Column<OrganizationMemberRecord>[] = [
    {
      key: 'name',
      header: t('manage.members.name'),
      render: (member) => (
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
            {member.user_name?.charAt(0)?.toUpperCase() || '?'}
          </div>
          <span className="font-medium text-foreground">
            {member.user_name || '-'}
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
      render: (member) => <span className="text-muted-foreground">{member.user_email}</span>,
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
    ...(canManage
      ? [
          {
            key: 'actions',
            header: t('managed.table.actions'),
            align: 'right' as const,
            truncate: false,
            render: (member: OrganizationMemberRecord) => renderMemberManageAction(member),
          },
        ]
      : []),
  ]
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.members.title')}
        subtitle={t('manage.members.subtitle', {
          organization: currentOrganization?.name || organizationId || '-',
        })}
        action={
          canManage ? (
            <Button size="sm" onClick={() => resetAddMemberDialog(true)}>
              <UserPlus className="mr-1 h-4 w-4" />
              {t('manage.members.add')}
            </Button>
          ) : null
        }
      />

      <Alert className="mb-4">
        <Info />
        <AlertDescription className="space-y-1">
          <p>{t('manage.members.accessExplanation')}</p>
          {!canManage ? <p>{t('manage.members.readOnlyExplanation')}</p> : null}
        </AlertDescription>
      </Alert>

      <FilterBar
        searchPlaceholder={t('manage.members.searchPlaceholder')}
        searchValue={memberSearch}
        onSearchChange={(value) => {
          resetMembersPagination()
          setMemberSearch(value)
        }}
        filters={filters}
      />

      <DataTable
        columns={columns}
        data={filteredMembers}
        loading={isLoading}
        fetching={isFetching}
        emptyMessage={t('manage.members.empty')}
        mobileCard={(member) => (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-medium text-primary">
                  {member.user_name?.charAt(0)?.toUpperCase() || '?'}
                </div>
                <div className="min-w-0">
                  <div className="truncate font-medium text-foreground">
                    {member.user_name || '-'}
                    {member.user_id === session?.data?.user?.id ? (
                      <span className="ml-1.5 text-xs text-muted-foreground">
                        ({t('manage.members.you')})
                      </span>
                    ) : null}
                  </div>
                  <div className="truncate text-sm text-muted-foreground">{member.user_email}</div>
                </div>
              </div>
              <span className="shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium">
                {roleLabel(t, member.role)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="text-muted-foreground">{t('manage.members.joined')}</span>
              {member.joined_at ? (
                <RelativeTime date={member.joined_at} />
              ) : (
                <span className="text-muted-foreground">-</span>
              )}
            </div>
            {renderMemberManageAction(member, true)}
          </div>
        )}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
      />

      {/* Add Existing Member Dialog */}
      <Dialog
        open={showAddMember}
        onOpenChange={(open) => {
          if (!addMemberMutation.isPending) resetAddMemberDialog(open)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.add')}</DialogTitle>
            <DialogDescription>
              {t('manage.members.addDescription', {
                organization: currentOrganization?.name || organizationId || '-',
              })}
            </DialogDescription>
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
                  disabled={addMemberMutation.isPending}
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
              {emailAlreadyMember ? (
                <p className="text-sm text-destructive">{t('manage.members.alreadyMember')}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {t('manage.members.registeredUserHint')}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.role')}</label>
              <Select value={role} onValueChange={setRole} disabled={addMemberMutation.isPending}>
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
              <p className="text-xs text-muted-foreground">
                {normalizeManagedRole(role) === 'admin'
                  ? t('manage.members.roleAdminImpact')
                  : t('manage.members.roleMemberImpact')}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => resetAddMemberDialog(false)}
              disabled={addMemberMutation.isPending}
            >
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleAddMember}
              disabled={!email.trim() || emailAlreadyMember || addMemberMutation.isPending}
            >
              {addMemberMutation.isPending ? t('common.loading') : t('manage.members.add')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manage Member Dialog */}
      <Dialog
        open={!!roleTarget}
        onOpenChange={(v) => {
          if (!v && !updateRoleMut.isPending) closeRoleDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.manage')}</DialogTitle>
            <DialogDescription>
              {t('manage.members.manageDescription', {
                member: roleTarget?.user_name || roleTarget?.user_email,
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.members.role')}</label>
              <Select value={newRole} onValueChange={setNewRole} disabled={updateRoleMut.isPending}>
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

            {normalizeManagedRole(roleTarget?.role) === 'member' &&
            normalizeManagedRole(newRole) === 'admin' ? (
              <Alert>
                <Info />
                <AlertDescription>{t('manage.members.promoteAdminImpact')}</AlertDescription>
              </Alert>
            ) : null}

            {normalizeManagedRole(roleTarget?.role) === 'admin' &&
            normalizeManagedRole(newRole) === 'member' ? (
              <Alert>
                <Info />
                <AlertDescription>{t('manage.members.demoteMemberImpact')}</AlertDescription>
              </Alert>
            ) : null}

            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
              <div className="font-medium text-foreground">{t('manage.members.remove')}</div>
              <p className="mt-1 text-sm text-muted-foreground">
                {t('manage.members.removeAccessImpact')}
              </p>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                className="mt-3"
                onClick={openRemoveFromRoleDialog}
                disabled={updateRoleMut.isPending}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t('manage.members.remove')}
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeRoleDialog} disabled={updateRoleMut.isPending}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleChangeRole}
              disabled={
                updateRoleMut.isPending ||
                normalizeManagedRole(newRole) === normalizeManagedRole(roleTarget?.role)
              }
            >
              {updateRoleMut.isPending ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Confirm Dialog */}
      <Dialog
        open={!!removeTarget}
        onOpenChange={(v) => {
          if (!v && !removeMemberMut.isPending) closeRemoveDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.members.remove')}</DialogTitle>
            <DialogDescription>
              {t('manage.members.removeConfirm', {
                member: removeTarget?.user_name || removeTarget?.user_email,
              })}
            </DialogDescription>
          </DialogHeader>
          <Alert variant="destructive">
            <Info />
            <AlertDescription>{t('manage.members.removeAccessImpact')}</AlertDescription>
          </Alert>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={closeRemoveDialog}
              disabled={removeMemberMut.isPending}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleRemove}
              disabled={removeMemberMut.isPending}
            >
              {removeMemberMut.isPending ? t('common.loading') : t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
