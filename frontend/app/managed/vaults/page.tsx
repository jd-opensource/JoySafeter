'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus } from 'lucide-react'
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

  const { data, isLoading, isFetching, isError, error, hasNext, hasPrev, page, pageSize, pageSizeOptions, goNext, goPrev, goToPage, setPageSize } =
    usePaginatedList<Vault>({
      queryKey: 'vaults',
      path: '/vaults',
      includeArchived: showArchived,
    })

  const archiveMutation = useMutation({
    mutationFn: (vault: Vault) =>
      managedPost(`/vaults/${stripIdPrefix(vault.id)}/archive`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      setArchiveTarget(null)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (vault: Vault) =>
      managedDelete(`/vaults/${stripIdPrefix(vault.id)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      setDeleteTarget(null)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const vaults = data.filter((v) =>
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

  const columns: Column<Vault>[] = [
    { key: 'id', header: t('managed.table.id'), render: (v) => <MonoId id={v.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (v) => (
        <span className="font-medium text-foreground">{v.name}</span>
      ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (v) => (
        <StatusBadge status={v.archived_at ? 'archived' : 'active'} />
      ),
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (v) => (
        <span className="text-muted-foreground text-xs">
          <RelativeTime date={v.created_at} />
        </span>
      ),
    },
  ]

  if (isError) {
    return <ResourceErrorState error={error} resource="vault" onRetry={() => queryClient.invalidateQueries({ queryKey: ['vaults'] })} />
  }

  return (
    <div>
      <PageHeader
        title={t('managed.vaults.title')}
        subtitle={t('managed.vaults.subtitle')}
        action={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="w-4 h-4" />
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
                  onClick: () => setArchiveTarget(v),
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
          if (archiveTarget) archiveMutation.mutate(archiveTarget)
        }}
        onCancel={() => setArchiveTarget(null)}
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
          if (deleteTarget) deleteMutation.mutate(deleteTarget)
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
