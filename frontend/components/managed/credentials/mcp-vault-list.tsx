'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

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
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseVaultResponse } from '@/lib/managed/vault-response-parsers'
import { parseCredentialGroupId } from '@/types/entity-id'
import type { Vault } from '@/types/managed'

interface VaultActionVariables {
  vault: Vault
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export interface McpVaultListState {
  searchQuery: string
  createdFilter: string
  showArchived: boolean
  pageSize: number
}

const DEFAULT_MCP_LIST_STATE: McpVaultListState = {
  searchQuery: '',
  createdFilter: 'all',
  showArchived: false,
  pageSize: 10,
}

export function McpVaultList({
  onCreate,
  state,
  onStateChange,
}: {
  onCreate: () => void
  state?: McpVaultListState
  onStateChange?: (state: McpVaultListState) => void
}) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [localState, setLocalState] = useState(DEFAULT_MCP_LIST_STATE)
  const listState = state ?? localState
  const updateListState = (patch: Partial<McpVaultListState>) => {
    const next = { ...listState, ...patch }
    if (state && onStateChange) onStateChange(next)
    else setLocalState(next)
  }
  const { showArchived, searchQuery, createdFilter } = listState
  const setShowArchived = (value: boolean) => updateListState({ showArchived: value })
  const setSearchQuery = (value: string) => updateListState({ searchQuery: value })
  const setCreatedFilter = (value: string) => updateListState({ createdFilter: value })
  const [archiveTarget, setArchiveTarget] = useState<Vault | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Vault | null>(null)
  const {
    scopeRef: managedScopeRef,
    scope: managedScope,
    readOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      setArchiveTarget(null)
      setDeleteTarget(null)
    },
  })

  const currentVaultIsActive = (vault: Vault, scope: string) =>
    scopeIsActive(scope) &&
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{
        data?: Vault[]
      }>({ queryKey: ['credential-groups', scope, '/credential-groups'] })
      .some(([, page]) => page?.data?.some((v) => v.id === vault.id && !v.archived_at))

  const openArchiveDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return
    bumpRun()
    setArchiveTarget(vault)
  }
  const closeArchiveDialog = () => {
    bumpRun()
    setArchiveTarget(null)
  }
  const openDeleteDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return
    bumpRun()
    setDeleteTarget(vault)
  }
  const closeDeleteDialog = () => {
    bumpRun()
    setDeleteTarget(null)
  }

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
  } = usePaginatedList<Vault>({
    queryKey: 'credential-groups',
    path: '/credential-groups',
    includeArchived: showArchived,
    pageSize: listState.pageSize,
    onPageSizeChange: (pageSize) => updateListState({ pageSize }),
    parseItem: parseVaultResponse,
    parseCursor: parseCredentialGroupId,
  })

  const archiveMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) throw new Error('Stale vault archive ignored')
      if (!currentProjectAllowsWrite()) throw new Error('Archived project vault archive ignored')
      return managedPost(
        apiResourcePath('credential-groups', vault.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setArchiveTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) throw new Error('Stale vault delete ignored')
      if (!currentProjectAllowsWrite()) throw new Error('Archived project vault delete ignored')
      return managedDelete(
        apiResourcePath('credential-groups', vault.id),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setDeleteTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  const vaults = data.filter(
    (v) =>
      (showArchived || !v.archived_at) &&
      filterByCreatedTime(v.created_at, createdFilter) &&
      matchesSearch(searchQuery, [v.id, v.name, v.archived_at ? 'archived' : 'active']),
  )
  const filters: FilterDef[] = [
    { ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter },
  ]

  useEffect(() => {
    const activeById = new Map(data.filter((v) => !v.archived_at).map((v) => [v.id, v]))
    setArchiveTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    setDeleteTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const columns: Column<Vault>[] = [
    { key: 'id', header: t('managed.table.id'), render: (v) => <MonoId id={v.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (v) => <span className="font-medium text-foreground">{v.name}</span>,
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (v) => <StatusBadge status={v.archived_at ? 'archived' : 'active'} />,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (v) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={v.created_at} />
        </span>
      ),
    },
  ]

  if (isError)
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        onRetry={() =>
          queryClient.invalidateQueries({ queryKey: ['credential-groups', managedScope.key] })
        }
      />
    )

  return (
    <div>
      {readOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button
            size="sm"
            onClick={() => {
              if (!currentProjectAllowsWrite()) return
              if (!scopeIsActive()) return
              onCreate()
            }}
          >
            <Plus className="h-4 w-4" />
            {t('managed.credentials.newMcpVault')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.search.vaults')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />
      <DataTable
        columns={columns}
        data={vaults}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(v) => router.push(`/managed/credentials/mcp/${v.id}`)}
        actionMenu={(v) =>
          readOnly || v.archived_at
            ? []
            : [
                { label: t('managed.vaults.archiveVault'), onClick: () => openArchiveDialog(v) },
                {
                  label: t('common.delete'),
                  destructive: true,
                  icon: <Trash2 className="h-3.5 w-3.5" />,
                  onClick: () => openDeleteDialog(v),
                },
              ]
        }
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
        emptyMessage={t('managed.vaults.empty')}
      />
      <ConfirmDialog
        open={!readOnly && !!archiveTarget}
        title={t('managed.vaults.archiveTitle')}
        description={t('managed.vaults.archiveDescription', { name: archiveTarget?.name })}
        confirmLabel={t('common.archive')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) {
            closeArchiveDialog()
            return
          }
          if (archiveTarget) {
            if (!currentVaultIsActive(archiveTarget, managedScopeRef.current)) {
              closeArchiveDialog()
              return
            }
            const action = beginAction()
            if (!action) {
              closeArchiveDialog()
              return
            }
            archiveMutation.mutate({
              vault: archiveTarget,
              runId: action.runId,
              scope: action.scope,
              requestScope: action.requestScope,
            })
          }
        }}
        onCancel={closeArchiveDialog}
      />
      <ConfirmDialog
        open={!readOnly && !!deleteTarget}
        title={t('managed.vaults.deleteTitle')}
        description={t('managed.vaults.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) {
            closeDeleteDialog()
            return
          }
          if (deleteTarget) {
            if (!currentVaultIsActive(deleteTarget, managedScopeRef.current)) {
              closeDeleteDialog()
              return
            }
            const action = beginAction()
            if (!action) {
              closeDeleteDialog()
              return
            }
            deleteMutation.mutate({
              vault: deleteTarget,
              runId: action.runId,
              scope: action.scope,
              requestScope: action.requestScope,
            })
          }
        }}
        onCancel={closeDeleteDialog}
      />
    </div>
  )
}
