'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, Check, Plus, RotateCcw, Star } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
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
import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
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

function displayId(value: string | null) {
  if (!value) return '—'
  return value
    .split('_')
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ')
}

export interface ModelConnectionListState {
  searchQuery: string
  createdFilter: string
  showArchived: boolean
  pageSize: number
}

const DEFAULT_MODEL_LIST_STATE: ModelConnectionListState = {
  searchQuery: '',
  createdFilter: 'all',
  showArchived: false,
  pageSize: 10,
}

export function ModelConnectionList({
  onCreate,
  state,
  onStateChange,
}: {
  onCreate: () => void
  state?: ModelConnectionListState
  onStateChange?: (state: ModelConnectionListState) => void
}) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [localState, setLocalState] = useState(DEFAULT_MODEL_LIST_STATE)
  const listState = state ?? localState
  const updateListState = (patch: Partial<ModelConnectionListState>) => {
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
    query: { kind: 'model' },
    includeArchived: showArchived,
    cacheVersion: catalogVersion || undefined,
    enabled: catalogReady,
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
          matchesSearch(searchQuery, [
            s.id,
            s.name,
            s.provider ?? '',
            s.protocol ?? '',
            s.model ?? '',
          ]),
      ),
    [createdFilter, list.data, searchQuery, showArchived],
  )
  const filters: FilterDef[] = [
    { ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter },
  ]

  const invalidate = (scope: string) => {
    queryClient.invalidateQueries({ queryKey: ['credentials', scope] })
    queryClient.invalidateQueries({ queryKey: ['compatible-secrets', scope] })
  }
  const handleSetDefault = async (s: Secret) => {
    if (projectReadOnly || mutationPending) return
    const current = list.data.find((item) => item.id === s.id)
    if (!current || current.kind !== 'model' || current.archived_at || current.is_default) return
    const action = beginAction()
    if (!action) return
    setMutationPending(true)
    try {
      await managedPost(
        apiResourcePath('credentials', current.id, 'default'),
        {},
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      invalidate(action.scope)
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setMutationPending(false)
    }
  }
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
      invalidate(action.scope)
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
      invalidate(action.scope)
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
      render: (s) => (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{s.name}</span>
            {s.is_default ? (
              <Badge variant="secondary" className="gap-1">
                <Check className="h-3 w-3" />
                {t('managed.secrets.default')}
              </Badge>
            ) : null}
          </div>
          {s.model ? <p className="text-xs text-muted-foreground">{s.model}</p> : null}
        </div>
      ),
    },
    {
      key: 'binding',
      header: t('managed.llm.providerProtocol'),
      render: (s) => (
        <div className="text-xs">
          <p className="font-medium text-foreground">{displayId(s.provider)}</p>
          <p className="text-muted-foreground">{displayId(s.protocol)}</p>
        </div>
      ),
    },
    {
      key: 'engines',
      header: t('managed.llm.compatibleEngines'),
      render: (s) => (
        <CompatibleEngineBadges engineIds={s.compatible_engine_ids} catalog={catalogQuery.data} />
      ),
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

  if (catalogQuery.isError)
    return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  if (!catalogReady) return <LlmCatalogPageState state="loading" />
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
            {t('managed.credentials.addModelConnection')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.credentials.searchModelsOnPage')}
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
                ...(s.kind === 'model' && !s.archived_at && !s.is_default
                  ? [
                      {
                        label: t('managed.secrets.setDefault'),
                        icon: <Star className="h-4 w-4" />,
                        onClick: () => handleSetDefault(s),
                      },
                    ]
                  : []),
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
        emptyMessage={t('managed.credentials.emptyModels')}
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
