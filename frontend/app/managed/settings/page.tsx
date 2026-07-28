'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Check, Trash2, Pencil, Crown } from 'lucide-react'
import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'

import {
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  type Column,
  type FilterDef,
  type MenuItem,
  PageHeader,
} from '@/components/managed/shared'
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
import { managedGet, managedPost, managedDelete, managedPut } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { canAdmin, canOwn, roleLabel } from '@/lib/managed/roles'
import { clearNonSessionQueryData } from '@/lib/query-client-lifecycle'
import { useProjectStore } from '@/stores/managed/project-store'
import type { ProjectInfo } from '@/stores/managed/project-store'

interface MeResponse {
  organization: {
    id: string
    name: string
    slug: string
    role: string
    created_at?: string
  }
  organizations: { id: string; name: string; slug: string; role: string; created_at?: string }[]
}

interface OrganizationRecord {
  id: string
  name: string
  slug: string
  logo?: string | null
  role: string
  created_at?: string | null
}

interface OrganizationMember {
  id: string
  user_id: string
  organization_id: string
  role: string
  user_name?: string | null
  user_email?: string | null
}

interface SwitchOrgVariables {
  orgId: string
  requestSeq: number
}

interface ScopedRun {
  runId: number
  scope: string
}

interface CreateOrgVariables {
  name: string
  runId: number
  scope: string
}

interface EditOrgVariables {
  orgId: string
  name: string
  runId: number
  scope: string
}

interface DeleteOrgVariables {
  orgId: string
  runId: number
  scope: string
}

interface TransferOwnershipVariables {
  orgId: string
  userId: string
  runId: number
  scope: string
}

export default function OrganizationPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const switchOrgRequestSeqRef = useRef(0)
  const createOrgRunRef = useRef(0)
  const editOrgRunRef = useRef(0)
  const deleteOrgRunRef = useRef(0)
  const transferOwnershipRunRef = useRef(0)
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const managedScopeRef = useRef(managedScope)
  const [showCreateOrg, setShowCreateOrg] = useState(false)
  const [newOrgName, setNewOrgName] = useState('')
  const [organizationSearch, setOrganizationSearch] = useState('')
  const [organizationCreatedFilter, setOrganizationCreatedFilter] = useState('all')

  const getCurrentManagedContext = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return {
      orgId,
      projectId,
      scope: `${orgId ?? ''}:${projectId ?? ''}`,
    }
  }
  const getCurrentManagedScope = () => getCurrentManagedContext().scope
  const isCurrentManagedScope = (scope: string) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope
  const nextScopedRun = (runRef: MutableRefObject<number>): ScopedRun => {
    const runId = runRef.current + 1
    runRef.current = runId
    return {
      runId,
      scope: managedScopeRef.current,
    }
  }
  const isCurrentScopedRun = (runRef: MutableRefObject<number>, action: ScopedRun) =>
    runRef.current === action.runId && isCurrentManagedScope(action.scope)

  const { data: me } = useQuery({
    queryKey: ['auth-me', currentOrgId, currentProjectId],
    queryFn: () => managedGet<MeResponse>('auth/me'),
  })

  const {
    data: organizations,
    isLoading: organizationsLoading,
    isFetching: organizationsFetching,
    hasNext: organizationsHasNext,
    hasPrev: organizationsHasPrev,
    page: organizationsPage,
    pageSize: organizationsPageSize,
    pageSizeOptions: organizationsPageSizeOptions,
    goNext: goNextOrganizations,
    goPrev: goPrevOrganizations,
    goToPage: goToOrganizationsPage,
    setPageSize: setOrganizationsPageSize,
    reset: resetOrganizationsPagination,
  } = usePaginatedList<OrganizationRecord>({
    queryKey: 'organizations-list',
    path: `/organizations${organizationSearch.trim() ? `?q=${encodeURIComponent(organizationSearch.trim())}` : ''}`,
  })

  const currentOrg = me?.organization
  const filteredOrganizations = organizations.filter((org) =>
    filterByCreatedTime(org.created_at || '', organizationCreatedFilter) &&
    matchesSearch(organizationSearch, [org.id, org.name, org.slug]),
  )

  const createOrgMutation = useMutation({
    mutationFn: async ({ name, scope }: CreateOrgVariables) => {
      if (!isCurrentManagedScope(scope)) {
        return undefined as unknown as { id: string; name: string; slug: string }
      }
      return managedPost<{ id: string; name: string; slug: string }>('auth/organizations', { name })
    },
    onSuccess: (_createdOrg, action) => {
      if (!isCurrentScopedRun(createOrgRunRef, action)) return
      resetOrganizationsPagination()
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      setShowCreateOrg(false)
      setNewOrgName('')
    },
    onError: (error, action) => {
      if (!isCurrentScopedRun(createOrgRunRef, action)) return
      toastOperationError(t, error, 'manage.organization.createFailed')
    },
  })

  const submitCreateOrg = () => {
    const name = newOrgName.trim()
    if (!name) return
    const action = nextScopedRun(createOrgRunRef)
    if (!isCurrentScopedRun(createOrgRunRef, action)) return
    createOrgMutation.mutate({ name, ...action })
  }

  const handleCreateOrgOpenChange = (open: boolean) => {
    if (!open) {
      createOrgRunRef.current += 1
    }
    setShowCreateOrg(open)
  }

  const switchOrgMutation = useMutation({
    mutationFn: ({ orgId }: SwitchOrgVariables) =>
      managedPost<{
        org_id?: string
        project_id?: string
        project?: ProjectInfo
        projects?: ProjectInfo[]
      }>(
        'auth/switch-context',
        { org_id: orgId },
        {
          skipManagedContext: true,
          headers: { 'X-Org-Id': orgId },
        },
      ),
    onSuccess: (data, { orgId, requestSeq }) => {
      if (requestSeq !== switchOrgRequestSeqRef.current) return
      const targetOrgId = data?.org_id || orgId
      const targetProjectId = data?.project?.id || data?.project_id
      const { setContext, setCurrentOrg, setCurrentProject } = useProjectStore.getState()
      if (targetProjectId && data?.project && data?.projects) {
        setContext(targetOrgId, targetProjectId, me?.organizations || organizations, data.projects, data.project)
      } else {
        setCurrentOrg(targetOrgId)
        if (targetProjectId) {
          setCurrentProject(targetProjectId)
        }
      }
      clearNonSessionQueryData(queryClient)
    },
    onError: (error, { requestSeq }) => {
      if (requestSeq !== switchOrgRequestSeqRef.current) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  const deleteOrgMutation = useMutation({
    mutationFn: async ({ orgId, scope }: DeleteOrgVariables) => {
      if (!isCurrentManagedScope(scope)) return undefined
      return managedDelete(`/organizations/${orgId}`)
    },
    onSuccess: (_result, action) => {
      if (!isCurrentScopedRun(deleteOrgRunRef, action)) return
      resetOrganizationsPagination()
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      setDeleteTarget(null)
    },
    onError: (error, action) => {
      if (!isCurrentScopedRun(deleteOrgRunRef, action)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const closeDeleteOrgDialog = () => {
    deleteOrgRunRef.current += 1
    setDeleteTarget(null)
  }

  const currentDeletableOrganization = (target: { id: string; name: string } | null) => {
    if (!target) return null
    const current = organizations.find((org) => org.id === target.id)
    if (current && canOwn(current.role) && current.id !== currentOrg?.id) {
      return { id: current.id, name: current.name }
    }
    return null
  }

  const currentEditableOrganization = (target: { id: string; name: string } | null) => {
    if (!target) return null
    const current = organizations.find((org) => org.id === target.id)
    return current && canAdmin(current.role) ? { id: current.id, name: current.name } : null
  }

  const currentTransferableOrganization = (target: { id: string; name: string } | null) => {
    if (!target) return null
    const current = organizations.find((org) => org.id === target.id)
    return current && canOwn(current.role) ? { id: current.id, name: current.name } : null
  }

  const submitDeleteOrg = () => {
    const target = currentDeletableOrganization(deleteTarget)
    if (!target) {
      closeDeleteOrgDialog()
      return
    }
    const action = nextScopedRun(deleteOrgRunRef)
    if (!isCurrentScopedRun(deleteOrgRunRef, action)) {
      closeDeleteOrgDialog()
      return
    }
    deleteOrgMutation.mutate({ orgId: target.id, ...action })
  }

  const [editTarget, setEditTarget] = useState<{ id: string; name: string } | null>(null)
  const [editName, setEditName] = useState('')
  const [transferTarget, setTransferTarget] = useState<{ id: string; name: string } | null>(null)
  const [selectedNewOwnerId, setSelectedNewOwnerId] = useState('')

  useEffect(() => {
    if (managedScopeRef.current === managedScope) return
    managedScopeRef.current = managedScope
    switchOrgRequestSeqRef.current += 1
    createOrgRunRef.current += 1
    editOrgRunRef.current += 1
    deleteOrgRunRef.current += 1
    transferOwnershipRunRef.current += 1
    setShowCreateOrg(false)
    setNewOrgName('')
    setDeleteTarget(null)
    setEditTarget(null)
    setEditName('')
    setTransferTarget(null)
    setSelectedNewOwnerId('')
  }, [managedScope])

  const editOrgMutation = useMutation({
    mutationFn: async ({ orgId, name, scope }: EditOrgVariables) => {
      if (!isCurrentManagedScope(scope)) return undefined
      return managedPut(`/organizations/${orgId}`, { name })
    },
    onSuccess: (_updatedOrg, action) => {
      if (!isCurrentScopedRun(editOrgRunRef, action)) return
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      setEditTarget(null)
      setEditName('')
    },
    onError: (error, action) => {
      if (!isCurrentScopedRun(editOrgRunRef, action)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const closeEditOrgDialog = () => {
    editOrgRunRef.current += 1
    setEditTarget(null)
  }

  const submitEditOrg = () => {
    const target = currentEditableOrganization(editTarget)
    if (!target) {
      closeEditOrgDialog()
      return
    }
    const name = editName.trim()
    if (!name) return
    const action = nextScopedRun(editOrgRunRef)
    if (!isCurrentScopedRun(editOrgRunRef, action)) {
      closeEditOrgDialog()
      return
    }
    editOrgMutation.mutate({ orgId: target.id, name, ...action })
  }

  const { data: transferMembers = [], isLoading: isLoadingTransferMembers } = useQuery({
    queryKey: ['organization-members', transferTarget?.id],
    queryFn: async () => {
      const response = await managedGet<{ data: OrganizationMember[] }>(
        `/organizations/${transferTarget!.id}/members`,
      )
      return response.data
    },
    enabled: !!transferTarget,
  })

  const transferCandidates = transferMembers.filter((member) => member.role !== 'owner')

  const currentTransferCandidate = (orgId: string, userId: string) =>
    queryClient
      .getQueryData<OrganizationMember[]>(['organization-members', orgId])
      ?.find((member) => member.user_id === userId && member.role !== 'owner') ?? null

  useEffect(() => {
    const currentById = new Map(organizations.map((org) => [org.id, org]))
    setEditTarget((target) => {
      if (!target) return null
      const current = currentById.get(target.id)
      if (!current || !canAdmin(current.role)) {
        editOrgRunRef.current += 1
        setEditName('')
        return null
      }
      return { id: current.id, name: current.name }
    })
    setDeleteTarget((target) => {
      if (!target) return null
      const current = currentById.get(target.id)
      if (current && canOwn(current.role) && current.id !== currentOrg?.id) {
        return { id: current.id, name: current.name }
      }
      deleteOrgRunRef.current += 1
      return null
    })
    setTransferTarget((target) => {
      if (!target) return null
      const current = currentById.get(target.id)
      if (!current || !canOwn(current.role)) {
        transferOwnershipRunRef.current += 1
        setSelectedNewOwnerId('')
        return null
      }
      return { id: current.id, name: current.name }
    })
  }, [currentOrg?.id, organizations])

  useEffect(() => {
    if (
      selectedNewOwnerId &&
      !transferCandidates.some((member) => member.user_id === selectedNewOwnerId)
    ) {
      setSelectedNewOwnerId('')
    }
  }, [selectedNewOwnerId, transferCandidates])

  const transferOwnershipMutation = useMutation({
    mutationFn: async ({ orgId, userId, scope }: TransferOwnershipVariables) => {
      if (!isCurrentManagedScope(scope)) return undefined
      return managedPost(`/organizations/${orgId}/transfer-ownership`, {
        new_owner_user_id: userId,
      })
    },
    onSuccess: (_result, action) => {
      if (!isCurrentScopedRun(transferOwnershipRunRef, action)) return
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      queryClient.invalidateQueries({ queryKey: ['organization-members', action.orgId] })
      setTransferTarget(null)
      setSelectedNewOwnerId('')
    },
    onError: (error, action) => {
      if (!isCurrentScopedRun(transferOwnershipRunRef, action)) return
      toastOperationError(t, error, 'manage.organization.transferFailed')
    },
  })

  const closeTransferOwnershipDialog = () => {
    transferOwnershipRunRef.current += 1
    setTransferTarget(null)
    setSelectedNewOwnerId('')
  }

  const submitTransferOwnership = () => {
    const target = currentTransferableOrganization(transferTarget)
    if (!target || !selectedNewOwnerId) {
      closeTransferOwnershipDialog()
      return
    }
    const candidate = currentTransferCandidate(target.id, selectedNewOwnerId)
    if (!candidate) {
      closeTransferOwnershipDialog()
      return
    }
    const action = nextScopedRun(transferOwnershipRunRef)
    if (!isCurrentScopedRun(transferOwnershipRunRef, action)) {
      closeTransferOwnershipDialog()
      return
    }
    transferOwnershipMutation.mutate({
      orgId: target.id,
      userId: candidate.user_id,
      ...action,
    })
  }

  useEffect(
    () => () => {
      switchOrgRequestSeqRef.current += 1
      createOrgRunRef.current += 1
      editOrgRunRef.current += 1
      deleteOrgRunRef.current += 1
      transferOwnershipRunRef.current += 1
    },
    [],
  )

  type Organization = OrganizationRecord

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: organizationCreatedFilter,
      onChange: setOrganizationCreatedFilter,
    },
  ]

  const columns: Column<Organization>[] = [
    {
      key: 'name',
      header: t('manage.organization.name'),
      render: (org) => {
        const isCurrent = org.id === currentOrg?.id
        return (
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground">{org.name}</span>
            {isCurrent && (
              <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
                <Check className="h-3 w-3" />
                {t('manage.organization.current')}
              </span>
            )}
          </div>
        )
      },
    },
    {
      key: 'slug',
      header: 'Slug',
      render: (org) => <MonoId id={org.slug} truncate={false} />,
    },
    {
      key: 'role',
      header: t('manage.members.role'),
      render: (org) => <span className="text-muted-foreground">{roleLabel(t, org.role)}</span>,
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (org) =>
        org.created_at ? (
          <RelativeTime date={org.created_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.organization.title')}
        subtitle={t('manage.organization.subtitle')}
        action={
          <Button size="sm" onClick={() => setShowCreateOrg(true)}>
            <Plus className="mr-1 h-4 w-4" />
            {t('manage.organization.create')}
          </Button>
        }
      />

      <FilterBar
        searchPlaceholder="按名称、Slug 或 ID 搜索组织"
        searchValue={organizationSearch}
        onSearchChange={(value) => {
          resetOrganizationsPagination()
          setOrganizationSearch(value)
        }}
        filters={filters}
      />

      <DataTable
        columns={columns}
        data={filteredOrganizations}
        loading={organizationsLoading}
        fetching={organizationsFetching}
        emptyMessage={t('manage.organization.empty')}
        pagination={{
          hasNext: organizationsHasNext,
          hasPrev: organizationsHasPrev,
          page: organizationsPage,
          pageSize: organizationsPageSize,
          pageSizeOptions: organizationsPageSizeOptions,
          onNext: goNextOrganizations,
          onPrev: goPrevOrganizations,
          onPageChange: goToOrganizationsPage,
          onPageSizeChange: setOrganizationsPageSize,
        }}
        actionMenu={(org) => {
          const isCurrent = org.id === currentOrg?.id
          const items: MenuItem[] = []

          if (canAdmin(org.role)) {
            items.push({
              label: t('common.edit'),
              icon: <Pencil className="h-3.5 w-3.5" />,
              onClick: () => {
                const current = currentEditableOrganization(org)
                if (!current) return
                editOrgRunRef.current += 1
                setEditTarget(current)
                setEditName(current.name)
              },
            })
          }

          if (!isCurrent) {
            items.push({
              label: t('manage.organization.switch'),
              onClick: () =>
                switchOrgMutation.mutate({
                  orgId: org.id,
                  requestSeq: (switchOrgRequestSeqRef.current += 1),
                }),
            })
          }

          if (canOwn(org.role)) {
            items.push({
              label: t('manage.organization.transferOwnership'),
              icon: <Crown className="h-3.5 w-3.5" />,
              onClick: () => {
                const current = currentTransferableOrganization(org)
                if (!current) return
                transferOwnershipRunRef.current += 1
                setTransferTarget(current)
                setSelectedNewOwnerId('')
              },
            })
          }

          if (canOwn(org.role) && !isCurrent) {
            items.push({
              label: t('common.delete'),
              icon: <Trash2 className="h-3.5 w-3.5" />,
              destructive: true,
              onClick: () => {
                const current = currentDeletableOrganization(org)
                if (!current) return
                deleteOrgRunRef.current += 1
                setDeleteTarget(current)
              },
            })
          }

          return items
        }}
      />

      {/* Create Organization Dialog */}
      <Dialog open={showCreateOrg} onOpenChange={handleCreateOrgOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.create')}</DialogTitle>
            <DialogDescription>{t('manage.organization.createDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.organization.name')}</label>
              <Input
                placeholder={t('manage.organization.namePlaceholder')}
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitCreateOrg()
                }}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => handleCreateOrgOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={submitCreateOrg}
              disabled={!newOrgName.trim() || createOrgMutation.isPending}
            >
              {createOrgMutation.isPending ? t('common.loading') : t('manage.organization.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Organization Dialog */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && closeDeleteOrgDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.delete')}</DialogTitle>
            <DialogDescription>
              {t('manage.organization.deleteConfirm', { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={closeDeleteOrgDialog}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={submitDeleteOrg}
              disabled={deleteOrgMutation.isPending}
            >
              {deleteOrgMutation.isPending ? t('common.loading') : t('manage.organization.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Organization Dialog */}
      <Dialog open={editTarget !== null} onOpenChange={(open) => !open && closeEditOrgDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.edit')}</DialogTitle>
            <DialogDescription>{t('manage.organization.editDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('manage.organization.name')}</label>
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder={t('manage.organization.namePlaceholder')}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeEditOrgDialog}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={submitEditOrg}
              disabled={!editName.trim() || editOrgMutation.isPending}
            >
              {editOrgMutation.isPending ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Transfer Ownership Dialog */}
      <Dialog
        open={transferTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            closeTransferOwnershipDialog()
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.transferOwnership')}</DialogTitle>
            <DialogDescription>{t('manage.organization.transferOwnershipDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {isLoadingTransferMembers ? (
              <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
            ) : transferCandidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('manage.organization.noTransferCandidates')}
              </p>
            ) : (
              <div className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
                {transferCandidates.map((member) => {
                  const label = member.user_name || member.user_email || member.user_id
                  return (
                    <button
                      key={member.user_id}
                      type="button"
                      className={`w-full px-3 py-2 text-left hover:bg-muted/60 ${selectedNewOwnerId === member.user_id ? 'bg-muted' : ''}`}
                      onClick={() => setSelectedNewOwnerId(member.user_id)}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-foreground">
                            {label}
                          </div>
                          {member.user_email && member.user_name && (
                            <div className="truncate text-xs text-muted-foreground">
                              {member.user_email}
                            </div>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {roleLabel(t, member.role)}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeTransferOwnershipDialog}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={submitTransferOwnership}
              disabled={!selectedNewOwnerId || transferOwnershipMutation.isPending}
            >
              {transferOwnershipMutation.isPending
                ? t('common.loading')
                : t('manage.organization.transferOwnership')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
