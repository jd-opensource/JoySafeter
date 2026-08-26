'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, RotateCcw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import {
  ConfirmDialog,
  RelativeTime,
  ResourceErrorState,
  StatusBadge,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { filterByCreatedTime, createCreatedTimeFilter, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { parseCredentialResponse } from '@/lib/managed/credential-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Credential } from '@/types/managed'

import { CredentialIdentity } from './credential-identity'
import { CredentialListPanel } from './credential-list-panel'

export interface ServiceCredentialListState {
  searchQuery: string
  createdFilter: string
  showArchived: boolean
  pageSize: number
}

const DEFAULT_SERVICE_LIST_STATE: ServiceCredentialListState = {
  searchQuery: '',
  createdFilter: 'all',
  showArchived: false,
  pageSize: 10,
}

export function ServiceCredentialList({
  onCreate,
  state,
  onStateChange,
}: {
  onCreate: () => void
  state?: ServiceCredentialListState
  onStateChange?: (state: ServiceCredentialListState) => void
}) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [localState, setLocalState] = useState(DEFAULT_SERVICE_LIST_STATE)
  const listState = state ?? localState
  const updateListState = (patch: Partial<ServiceCredentialListState>) => {
    const next = { ...listState, ...patch }
    if (state && onStateChange) onStateChange(next)
    else setLocalState(next)
  }
  const { searchQuery, createdFilter, showArchived } = listState
  const setSearchQuery = (value: string) => updateListState({ searchQuery: value })
  const setCreatedFilter = (value: string) => updateListState({ createdFilter: value })
  const setShowArchived = (value: boolean) => updateListState({ showArchived: value })
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null)
  const [lifecycleTarget, setLifecycleTarget] = useState<{
    credential: Credential
    action: 'archive' | 'restore'
  } | null>(null)
  const [mutationPending, setMutationPending] = useState(false)
  const {
    scope: managedScope,
    readOnly: projectReadOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      setDeleteTarget(null)
      setLifecycleTarget(null)
      setMutationPending(false)
    },
  })

  const list = usePaginatedList<Credential>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'service' },
    includeArchived: showArchived,
    pageSize: listState.pageSize,
    onPageSizeChange: (pageSize) => updateListState({ pageSize }),
    parseItem: parseCredentialResponse,
    parseCursor: parseCredentialId,
  })

  const filtered = useMemo(
    () =>
      list.data.filter(
        (s) =>
          (showArchived || !s.archived_at) &&
          filterByCreatedTime(s.created_at, createdFilter) &&
          matchesSearch(searchQuery, [s.id, s.name]),
      ),
    [createdFilter, list.data, searchQuery, showArchived],
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t, ['7d', '30d', '90d']),
      value: createdFilter,
      onChange: (value) => {
        setCreatedFilter(value)
        list.goToPage(1)
      },
    },
  ]

  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly || mutationPending) return
    const current = list.data.find((item) => item.id === deleteTarget.id)
    if (!current) {
      setDeleteTarget(null)
      return
    }
    const action = beginAction()
    if (!action) {
      setDeleteTarget(null)
      return
    }
    setMutationPending(true)
    try {
      await managedDelete(
        apiResourcePath('credentials', current.id),
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      queryClient.invalidateQueries({ queryKey: ['credentials', action.scope] })
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(action.runId, action.scope)) {
        setMutationPending(false)
        setDeleteTarget(null)
      }
    }
  }
  const handleLifecycle = async () => {
    if (!lifecycleTarget || projectReadOnly || mutationPending) return
    const target = lifecycleTarget
    const current = list.data.find((item) => item.id === target.credential.id)
    const statusMatches =
      target.action === 'restore' ? Boolean(current?.archived_at) : !current?.archived_at
    if (!current || !statusMatches) {
      setLifecycleTarget(null)
      return
    }
    const action = beginAction()
    if (!action) {
      setLifecycleTarget(null)
      return
    }
    setMutationPending(true)
    try {
      await managedPost(
        apiResourcePath('credentials', current.id, target.action),
        {},
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      queryClient.invalidateQueries({ queryKey: ['credentials', action.scope] })
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(action.runId, action.scope)) {
        setMutationPending(false)
        setLifecycleTarget(null)
      }
    }
  }

  const columns: Column<Credential>[] = [
    {
      key: 'identity',
      header: t('managed.credentials.tabs.services'),
      render: (s) => (
        <CredentialIdentity
          name={s.name}
          publicId={s.id}
          badges={s.archived_at ? <StatusBadge status="archived" /> : undefined}
        />
      ),
      width: '65%',
      truncate: false,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={s.created_at} />
        </span>
      ),
    },
  ]

  const rowActions = (s: Credential) =>
    projectReadOnly || mutationPending
      ? []
      : [
          ...(s.archived_at
            ? [
                {
                  label: t('common.restore'),
                  icon: <RotateCcw className="size-4" />,
                  onClick: () => {
                    bumpRun()
                    setLifecycleTarget({ credential: s, action: 'restore' as const })
                  },
                },
              ]
            : [
                {
                  label: t('common.archive'),
                  icon: <Archive className="size-4" />,
                  onClick: () => {
                    bumpRun()
                    setLifecycleTarget({ credential: s, action: 'archive' as const })
                  },
                },
              ]),
          {
            label: t('common.delete'),
            onClick: () => {
              bumpRun()
              setDeleteTarget(s)
            },
            destructive: true,
          },
        ]

  if (list.isError)
    return (
      <ResourceErrorState
        error={list.error}
        resource="credential"
        onRetry={() =>
          queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
        }
      />
    )

  return (
    <div>
      <CredentialListPanel
        searchPlaceholder={t('managed.credentials.searchServices')}
        searchValue={searchQuery}
        onSearchChange={(value) => {
          setSearchQuery(value)
          list.goToPage(1)
        }}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={(value) => {
          setShowArchived(value)
          list.goToPage(1)
        }}
        createAction={
          projectReadOnly
            ? undefined
            : {
                label: t('managed.credentials.createServiceCredential'),
                onClick: () => {
                  if (!scopeIsActive() || !currentProjectAllowsWrite()) return
                  onCreate()
                },
              }
        }
        emptyState={{
          title: t('managed.credentials.emptyServicesTitle'),
          description: t('managed.credentials.emptyServicesDescription'),
        }}
        noResultsState={{
          title: t('managed.credentials.noServiceResultsTitle'),
          description: t('managed.credentials.noResultsDescription'),
        }}
        onClearFilters={() => {
          updateListState({ searchQuery: '', createdFilter: 'all', showArchived: false })
          list.goToPage(1)
        }}
        columns={columns}
        data={filtered}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(s) => {
          if (scopeIsActive()) router.push(`/managed/credentials/${s.id}`)
        }}
        actionMenu={rowActions}
        mobileCard={(s) => (
          <div className="flex flex-col gap-3">
            <CredentialIdentity
              name={s.name}
              publicId={s.id}
              badges={s.archived_at ? <StatusBadge status="archived" /> : undefined}
            />
            <div className="text-xs">
              <div className="text-muted-foreground">{t('managed.table.created')}</div>
              <div className="mt-1 text-foreground">
                <RelativeTime date={s.created_at} />
              </div>
            </div>
          </div>
        )}
        pagination={{
          hasNext: list.hasNext,
          hasPrev: list.hasPrev,
          page: list.page,
          pageSize: list.pageSize,
          pageSizeOptions: list.pageSizeOptions,
          onNext: list.goNext,
          onPrev: list.goPrev,
          onPageChange: list.goToPage,
          onPageSizeChange: list.setPageSize,
        }}
      />
      <ConfirmDialog
        open={!projectReadOnly && Boolean(lifecycleTarget)}
        title={t(
          lifecycleTarget?.action === 'restore'
            ? 'managed.credentials.resources.restoreTitle'
            : 'managed.credentials.resources.archiveTitle',
        )}
        description={t(
          lifecycleTarget?.action === 'restore'
            ? 'managed.credentials.resources.restoreDescription'
            : 'managed.credentials.resources.archiveDescription',
          { name: lifecycleTarget?.credential.name },
        )}
        confirmLabel={t(
          lifecycleTarget?.action === 'restore' ? 'common.restore' : 'common.archive',
        )}
        onConfirm={handleLifecycle}
        onCancel={() => {
          bumpRun()
          setLifecycleTarget(null)
        }}
      />
      <ConfirmDialog
        open={!projectReadOnly && Boolean(deleteTarget)}
        title={t('managed.credentials.resources.deleteTitle')}
        description={t('managed.credentials.resources.deleteDescription', {
          name: deleteTarget?.name,
        })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => {
          bumpRun()
          setDeleteTarget(null)
        }}
      />
    </div>
  )
}
