'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedPost } from '@/lib/api-client'
import type { MemoryStore } from '@/types/managed'
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
  ResourceErrorState,
} from '@/components/managed/shared'
import { CreateMemoryStoreDialog } from './components/create-memory-store-dialog'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'

export default function MemoryStoreListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')

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
  } = usePaginatedList<MemoryStore>({
    queryKey: 'memory-stores',
    path: '/memory_stores',
    includeArchived: showArchived,
  })

  const stores = data.filter(
    (s) =>
      (showArchived || !s.archived_at) &&
      filterByCreatedTime(s.created_at, createdFilter) &&
      matchesSearch(searchQuery, [
        s.id,
        s.name,
        s.description,
        s.archived_at ? 'archived' : 'active',
      ]),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['memory-stores'] })

  const handleArchive = async (store: MemoryStore) => {
    try {
      await managedPost(`memory_stores/${store.id.replace('memstore_', '')}/archive`)
      invalidate()
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const columns: Column<MemoryStore>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (s) => <MonoId id={s.id} />,
    },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => <span className="font-medium text-foreground">{s.name}</span>,
    },
    {
      key: 'description',
      header: t('managed.memoryStores.descriptionLabel'),
      render: (s) => <span className="text-sm text-muted-foreground">{s.description || '-'}</span>,
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (s) => <StatusBadge status={s.archived_at ? 'archived' : 'active'} />,
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

  if (isError) {
    return <ResourceErrorState error={error} resource="memoryStore" onRetry={invalidate} />
  }

  return (
    <div>
      <PageHeader
        title={t('managed.memoryStores.title')}
        subtitle={t('managed.memoryStores.subtitle')}
        action={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('managed.memoryStores.new')}
          </Button>
        }
      />

      <FilterBar
        searchPlaceholder={t('managed.search.memoryStores')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />

      <DataTable
        columns={columns}
        data={stores}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(s) => router.push(`/managed/memory-stores/${s.id}`)}
        actionMenu={(s) =>
          s.archived_at
            ? []
            : [{ label: t('managed.memoryStores.archiveStore'), onClick: () => handleArchive(s) }]
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
        emptyMessage={t('managed.memoryStores.empty')}
      />

      <CreateMemoryStoreDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => invalidate()}
      />
    </div>
  )
}
