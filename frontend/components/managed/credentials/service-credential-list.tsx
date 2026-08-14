'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, Plus, RotateCcw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  StatusBadge,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { parseSecretResponse } from '@/lib/managed/secret-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Secret } from '@/types/managed'

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
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)
  const [lifecycleTarget, setLifecycleTarget] = useState<{
    credential: Secret
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

  const list = usePaginatedList<Secret>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'service' },
    includeArchived: showArchived,
    pageSize: listState.pageSize,
    onPageSizeChange: (pageSize) => updateListState({ pageSize }),
    parseItem: parseSecretResponse,
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
    { ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter },
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

  const columns: Column<Secret>[] = [
    { key: 'id', header: t('managed.table.id'), render: (s) => <MonoId id={s.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => <span className="font-medium text-foreground">{s.name}</span>,
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
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (s) => <StatusBadge status={s.archived_at ? 'archived' : 'active'} />,
    },
  ]

  if (list.isError)
    return (
      <ResourceErrorState
        error={list.error}
        resource="secret"
        onRetry={() =>
          queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
        }
      />
    )

  return (
    <div>
      {projectReadOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button
            size="sm"
            onClick={() => {
              if (!scopeIsActive() || !currentProjectAllowsWrite()) return
              onCreate()
            }}
          >
            <Plus className="h-4 w-4" />
            {t('managed.credentials.addServiceCredential')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.credentials.searchServicesOnPage')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />
      <DataTable
        columns={columns}
        data={filtered}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(s) => {
          if (scopeIsActive()) router.push(`/managed/credentials/${s.id}`)
        }}
        actionMenu={(s) =>
          projectReadOnly || mutationPending
            ? []
            : [
                ...(s.archived_at
                  ? [
                      {
                        label: t('common.restore'),
                        icon: <RotateCcw className="h-4 w-4" />,
                        onClick: () => {
                          bumpRun()
                          setLifecycleTarget({ credential: s, action: 'restore' as const })
                        },
                      },
                    ]
                  : [
                      {
                        label: t('common.archive'),
                        icon: <Archive className="h-4 w-4" />,
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
        }
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
        emptyMessage={t('managed.credentials.emptyServices')}
      />
      <ConfirmDialog
        open={!projectReadOnly && Boolean(lifecycleTarget)}
        title={t(
          lifecycleTarget?.action === 'restore'
            ? 'managed.secrets.restoreTitle'
            : 'managed.secrets.archiveTitle',
        )}
        description={t(
          lifecycleTarget?.action === 'restore'
            ? 'managed.secrets.restoreDescription'
            : 'managed.secrets.archiveDescription',
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
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', { name: deleteTarget?.name })}
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
