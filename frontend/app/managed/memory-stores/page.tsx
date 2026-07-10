'use client'

import { useEffect, useRef, useState } from 'react'
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
import { useProjectStore } from '@/stores/managed/project-store'

export default function MemoryStoreListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const actionRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope)
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

  useEffect(() => {
    if (managedScopeRef.current !== managedScope) {
      actionRunRef.current += 1
    }
    managedScopeRef.current = managedScope
  }, [managedScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    managedScopeRef.current === scope &&
    currentManagedScopeIsActive(scope)

  const handleArchive = async (store: MemoryStore) => {
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    const storeStillCurrent = queryClient
      .getQueriesData<{ data?: MemoryStore[] }>({
        queryKey: ['memory-stores', actionScope, '/memory_stores'],
      })
      .some(([, page]) => page?.data?.some((currentStore) => currentStore.id === store.id))
    if (!storeStillCurrent) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    try {
      await managedPost(`memory_stores/${store.id.replace('memstore_', '')}/archive`)
      if (!isCurrentAction(runId, actionScope)) return
      invalidate()
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
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
