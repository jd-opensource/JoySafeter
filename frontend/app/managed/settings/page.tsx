'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, Check, Eye, Plus, Settings2 } from 'lucide-react'
import Link from 'next/link'
import { useRef, useState } from 'react'

import {
  DataTable,
  FilterBar,
  MonoId,
  PageHeader,
  RelativeTime,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { canAdmin, roleLabel } from '@/lib/managed/roles'
import {
  parseOrganizationInfo,
  parseSwitchContextResponse,
  type OrganizationInfoPayload,
  type SwitchContextResponsePayload,
} from '@/lib/managed/tenant-response-parsers'
import { resetManagedScopeQueries } from '@/lib/query-client-lifecycle'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrgInfo } from '@/stores/managed/project-store'
import { parseOrganizationId, type OrganizationId } from '@/types/entity-id'

type OrganizationRecord = OrgInfo

interface CreateOrganizationVariables {
  name: string
  runId: number
  scope: string
}

interface SwitchOrganizationVariables {
  orgId: OrganizationId
  requestSeq: number
}

export default function OrganizationPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const managedScope = JSON.stringify([currentOrgId, currentProjectId])
  const createRunRef = useRef(0)
  const switchRequestSeqRef = useRef(0)
  const switchInFlightOrgIdRef = useRef<OrganizationId | null>(null)
  const [showCreateOrganization, setShowCreateOrganization] = useState(false)
  const [newOrganizationName, setNewOrganizationName] = useState('')
  const [organizationSearch, setOrganizationSearch] = useState('')
  const [organizationCreatedFilter, setOrganizationCreatedFilter] = useState('all')
  const [switchingOrganizationId, setSwitchingOrganizationId] = useState<OrganizationId | null>(
    null,
  )

  const {
    data: organizations,
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
    reset: resetOrganizationsPagination,
  } = usePaginatedList<OrganizationRecord>({
    queryKey: 'organizations-list',
    path: `/organizations${organizationSearch.trim() ? `?q=${encodeURIComponent(organizationSearch.trim())}` : ''}`,
    parseItem: (item) => parseOrganizationInfo(item as OrganizationInfoPayload),
    parseCursor: parseOrganizationId,
  })

  const filteredOrganizations = organizations.filter(
    (organization) =>
      filterByCreatedTime(organization.created_at || '', organizationCreatedFilter) &&
      matchesSearch(organizationSearch, [
        organization.id,
        organization.name,
        organization.slug,
        organization.owner_name || '',
        organization.owner_email || '',
      ]),
  )

  const createOrganizationMutation = useMutation({
    mutationFn: ({ name, scope }: CreateOrganizationVariables) => {
      const state = useProjectStore.getState()
      if (JSON.stringify([state.currentOrgId, state.currentProjectId]) !== scope) {
        throw new Error('Stale organization creation ignored')
      }
      return managedPost<{ id: string; name: string; slug: string }>('organizations', { name })
    },
    onSuccess: (_organization, variables) => {
      if (variables.runId !== createRunRef.current || variables.scope !== managedScope) return
      resetOrganizationsPagination()
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      setShowCreateOrganization(false)
      setNewOrganizationName('')
    },
    onError: (error, variables) => {
      if (variables.runId !== createRunRef.current || variables.scope !== managedScope) return
      toastOperationError(t, error, 'manage.organization.createFailed')
    },
  })

  const switchOrganizationMutation = useMutation({
    mutationFn: async ({ orgId }: SwitchOrganizationVariables) =>
      parseSwitchContextResponse(
        await managedPost<SwitchContextResponsePayload>(
          'auth/switch-context',
          { org_id: orgId },
          { skipManagedContext: true, headers: { 'X-Org-Id': orgId } },
        ),
      ),
    onSuccess: (data, variables) => {
      if (variables.requestSeq !== switchRequestSeqRef.current) return
      const state = useProjectStore.getState()
      switchInFlightOrgIdRef.current = null
      setSwitchingOrganizationId(null)
      state.setContext(
        data.org_id,
        data.project_id,
        state.organizations.length ? state.organizations : organizations,
        data.projects,
        data.project,
      )
      resetManagedScopeQueries(queryClient)
    },
    onError: (error, variables) => {
      if (variables.requestSeq !== switchRequestSeqRef.current) return
      switchInFlightOrgIdRef.current = null
      setSwitchingOrganizationId(null)
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const switchOrganization = (orgId: OrganizationId) => {
    if (orgId === currentOrgId || switchInFlightOrgIdRef.current !== null) return
    switchInFlightOrgIdRef.current = orgId
    setSwitchingOrganizationId(orgId)
    switchOrganizationMutation.mutate({
      orgId,
      requestSeq: (switchRequestSeqRef.current += 1),
    })
  }

  const submitCreateOrganization = () => {
    const name = newOrganizationName.trim()
    if (!name) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    createOrganizationMutation.mutate({ name, runId, scope: managedScope })
  }

  const ownershipLabel = (organization: OrganizationRecord) => {
    if (organization.role === 'owner') return t('sidebar.ownedByYou')
    const ownerIdentity = organization.owner_name || organization.owner_email
    return ownerIdentity
      ? `${t('manage.organization.ownedBy')} ${ownerIdentity}`
      : t('manage.organization.ownerUnknown')
  }

  const renderActions = (organization: OrganizationRecord, fullWidth = false) => {
    const isCurrent = organization.id === currentOrgId
    const detailLabel = canAdmin(organization.role)
      ? t('manage.organization.manage')
      : t('manage.organization.view')
    const DetailIcon = canAdmin(organization.role) ? Settings2 : Eye

    return (
      <div className={fullWidth ? 'grid gap-2 sm:grid-cols-2' : 'flex justify-end gap-2'}>
        <Button asChild variant="outline" size="sm" className={fullWidth ? 'w-full' : undefined}>
          <Link href={`/managed/settings/organizations/${organization.id}`}>
            <DetailIcon className="size-3.5" />
            {detailLabel}
          </Link>
        </Button>
        {!isCurrent ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className={fullWidth ? 'w-full' : undefined}
            disabled={switchingOrganizationId !== null}
            onClick={() => switchOrganization(organization.id)}
          >
            <ArrowRightLeft className="size-3.5" />
            {switchingOrganizationId === organization.id
              ? t('manage.organization.switching')
              : t('manage.organization.switch')}
          </Button>
        ) : null}
      </div>
    )
  }

  const columns: Column<OrganizationRecord>[] = [
    {
      key: 'name',
      header: t('manage.organization.name'),
      render: (organization) => (
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-foreground">{organization.name}</span>
            {organization.id === currentOrgId ? (
              <span className="inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
                <Check className="size-3" />
                {t('manage.organization.current')}
              </span>
            ) : null}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {ownershipLabel(organization)}
          </div>
        </div>
      ),
    },
    {
      key: 'slug',
      header: 'Slug',
      render: (organization) => <MonoId id={organization.slug} truncate={false} />,
    },
    {
      key: 'role',
      header: t('manage.members.role'),
      render: (organization) => (
        <span className="text-muted-foreground">{roleLabel(t, organization.role)}</span>
      ),
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (organization) =>
        organization.created_at ? (
          <RelativeTime date={organization.created_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
    {
      key: 'actions',
      header: t('managed.table.actions'),
      align: 'right',
      truncate: false,
      render: (organization) => renderActions(organization),
    },
  ]

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: organizationCreatedFilter,
      onChange: setOrganizationCreatedFilter,
    },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.organization.title')}
        subtitle={t('manage.organization.subtitle')}
        action={
          <Button size="sm" onClick={() => setShowCreateOrganization(true)}>
            <Plus className="mr-1 size-4" />
            {t('manage.organization.create')}
          </Button>
        }
      />

      <FilterBar
        searchPlaceholder={t('manage.organization.searchPlaceholder')}
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
        loading={isLoading}
        fetching={isFetching}
        emptyMessage={t('manage.organization.empty')}
        mobileCard={(organization) => (
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-foreground">{organization.name}</span>
                {organization.id === currentOrgId ? (
                  <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
                    <Check className="size-3" />
                    {t('manage.organization.current')}
                  </span>
                ) : null}
              </div>
              <div className="text-xs text-muted-foreground">{ownershipLabel(organization)}</div>
              <MonoId id={organization.slug} truncate={false} />
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">{t('manage.members.role')}</div>
                <div className="text-foreground">{roleLabel(t, organization.role)}</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">{t('managed.table.created')}</div>
                <div className="text-foreground">
                  {organization.created_at ? <RelativeTime date={organization.created_at} /> : '-'}
                </div>
              </div>
            </div>
            {renderActions(organization, true)}
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

      <Dialog
        open={showCreateOrganization}
        onOpenChange={(open) => {
          if (!open) createRunRef.current += 1
          setShowCreateOrganization(open)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.organization.create')}</DialogTitle>
            <DialogDescription>{t('manage.organization.createDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <label className="text-sm font-medium">{t('manage.organization.name')}</label>
            <Input
              placeholder={t('manage.organization.namePlaceholder')}
              value={newOrganizationName}
              onChange={(event) => setNewOrganizationName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitCreateOrganization()
              }}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateOrganization(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={submitCreateOrganization}
              disabled={!newOrganizationName.trim() || createOrganizationMutation.isPending}
            >
              {createOrganizationMutation.isPending ? t('common.loading') : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
