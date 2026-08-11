'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus, Trash2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import type { Vault } from '@/types/managed'
import { managedPost, managedDelete } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { toastError } from '@/lib/utils/toast'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { Button } from '@/components/ui/button'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  StatusBadge,
  MonoId,
  RelativeTime,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { CreateVaultDialog } from './components/create-vault-dialog'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'

interface VaultActionVariables {
  vault: Vault
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export default function VaultListPage() {
  const { t } = useTranslation()
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [archiveTarget, setArchiveTarget] = useState<Vault | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Vault | null>(null)
  const router = useRouter()
  const queryClient = useQueryClient()
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
      setCreateOpen(false)
      setArchiveTarget(null)
      setDeleteTarget(null)
    },
  })

  // Guard actions on a vault row. The row object itself is the source of
  // truth for archived state — re-deriving it from the paginated-list query
  // cache was fragile (the cache key includes cursor/pageSize/includeArchived,
  // so prefix lookups missed rows off the current page, silently blocking
  // delete/archive with no feedback). We only require the scope to still be
  // active (no stale cross-project action) and write permission.
  const currentVaultIsActive = (_vault: Vault, scope: string) =>
    scopeIsActive(scope) && currentProjectAllowsWrite()

  const openArchiveDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) {
      toastError(t('managed.vaults.actionUnavailable'))
      return
    }
    bumpRun()
    setArchiveTarget(vault)
  }

  const closeArchiveDialog = () => {
    bumpRun()
    setArchiveTarget(null)
  }

  const openDeleteDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) {
      toastError(t('managed.vaults.actionUnavailable'))
      return
    }
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
    queryKey: 'vaults',
    path: '/vaults',
    includeArchived: showArchived,
  })

  const archiveMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault archive ignored')
      }
      return managedPost(
        apiResourcePath('vaults', vault.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults', scope] })
      setArchiveTarget(null)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault delete ignored')
      }
      return managedDelete(apiResourcePath('vaults', vault.id), managedRequestOptions(requestScope))
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults', scope] })
      setDeleteTarget(null)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const vaults = data.filter(
    (v) =>
      (showArchived || !v.archived_at) &&
      filterByCreatedTime(v.created_at, createdFilter) &&
      matchesSearch(searchQuery, [v.id, v.name, v.archived_at ? 'archived' : 'active']),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  useEffect(() => {
    const activeById = new Map(
      data.filter((vault) => !vault.archived_at).map((vault) => [vault.id, vault]),
    )
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

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['vaults', managedScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.vaults.title')}
        subtitle={t('managed.vaults.subtitle')}
        action={
          readOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                if (!currentProjectAllowsWrite()) return
                if (!scopeIsActive()) return
                setCreateOpen(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.vaults.new')}
            </Button>
          )
        }
      />

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
        onRowClick={(v) => router.push(`/managed/vaults/${v.id}`)}
        actionMenu={(v) =>
          readOnly || v.archived_at
            ? []
            : [
                {
                  label: t('managed.vaults.archiveVault'),
                  onClick: () => openArchiveDialog(v),
                },
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

      <CreateVaultDialog
        open={!readOnly && createOpen}
        onOpenChange={(open) => {
          if (open && !currentProjectAllowsWrite()) return
          if (open && !scopeIsActive()) return
          setCreateOpen(open)
        }}
      />

      <ConfirmDialog
        open={!readOnly && !!archiveTarget}
        title={t('managed.vaults.archiveTitle')}
        description={t('managed.vaults.archiveDescription', {
          name: archiveTarget?.name,
        })}
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
        description={t('managed.vaults.deleteDescription', {
          name: deleteTarget?.name,
        })}
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
