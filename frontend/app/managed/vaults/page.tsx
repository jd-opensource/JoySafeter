'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus, Trash2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import type { Vault } from '@/types/managed'
import { managedPost, managedDelete } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
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
import { useProjectStore } from '@/stores/managed/project-store'

interface VaultActionVariables {
  vault: Vault
  runId: number
  scope: string
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
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const actionRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope)

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId && currentManagedScopeIsActive(scope)

  const currentVaultIsActive = (vault: Vault, scope: string) =>
    currentManagedScopeIsActive(scope) &&
    queryClient
      .getQueriesData<{ data?: Vault[] }>({ queryKey: ['vaults', scope, '/vaults'] })
      .some(([, page]) =>
        page?.data?.some((currentVault) => currentVault.id === vault.id && !currentVault.archived_at),
      )

  const openArchiveDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return

    actionRunRef.current += 1
    setArchiveTarget(vault)
  }

  const closeArchiveDialog = () => {
    actionRunRef.current += 1
    setArchiveTarget(null)
  }

  const openDeleteDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return

    actionRunRef.current += 1
    setDeleteTarget(vault)
  }

  const closeDeleteDialog = () => {
    actionRunRef.current += 1
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
    mutationFn: ({ vault, runId, scope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault archive ignored')
      }
      return managedPost(`/vaults/${stripIdPrefix(vault.id)}/archive`, {})
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      setArchiveTarget(null)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ vault, runId, scope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault delete ignored')
      }
      return managedDelete(`/vaults/${stripIdPrefix(vault.id)}`)
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
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
    if (managedScopeRef.current !== managedScope) {
      actionRunRef.current += 1
      setArchiveTarget(null)
      setDeleteTarget(null)
    }
    managedScopeRef.current = managedScope
  }, [managedScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    const activeById = new Map(
      data.filter((vault) => !vault.archived_at).map((vault) => [vault.id, vault]),
    )
    setArchiveTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) actionRunRef.current += 1
      return current
    })
    setDeleteTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) actionRunRef.current += 1
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
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['vaults'] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.vaults.title')}
        subtitle={t('managed.vaults.subtitle')}
        action={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('managed.vaults.new')}
          </Button>
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
          v.archived_at
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

      <CreateVaultDialog open={createOpen} onOpenChange={setCreateOpen} />

      <ConfirmDialog
        open={!!archiveTarget}
        title={t('managed.vaults.archiveTitle')}
        description={t('managed.vaults.archiveDescription', {
          name: archiveTarget?.name,
        })}
        confirmLabel={t('common.archive')}
        destructive
        onConfirm={() => {
          if (archiveTarget) {
            const scope = managedScopeRef.current
            if (!currentVaultIsActive(archiveTarget, scope)) {
              closeArchiveDialog()
              return
            }
            const runId = actionRunRef.current + 1
            actionRunRef.current = runId
            archiveMutation.mutate({
              vault: archiveTarget,
              runId,
              scope,
            })
          }
        }}
        onCancel={closeArchiveDialog}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        title={t('managed.vaults.deleteTitle')}
        description={t('managed.vaults.deleteDescription', {
          name: deleteTarget?.name,
        })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={() => {
          if (deleteTarget) {
            const scope = managedScopeRef.current
            if (!currentVaultIsActive(deleteTarget, scope)) {
              closeDeleteDialog()
              return
            }
            const runId = actionRunRef.current + 1
            actionRunRef.current = runId
            deleteMutation.mutate({
              vault: deleteTarget,
              runId,
              scope,
            })
          }
        }}
        onCancel={closeDeleteDialog}
      />
    </div>
  )
}
