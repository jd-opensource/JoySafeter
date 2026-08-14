'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretResponse } from '@/lib/managed/secret-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Secret } from '@/types/managed'

export function ServiceCredentialList({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const list = usePaginatedList<Secret>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'service' },
    parseItem: parseSecretResponse,
    parseCursor: parseCredentialId,
  })

  const filtered = useMemo(
    () =>
      list.data.filter(
        (s) => filterByCreatedTime(s.created_at, createdFilter) && matchesSearch(searchQuery, [s.id, s.name]),
      ),
    [createdFilter, list.data, searchQuery],
  )
  const filters: FilterDef[] = [{ ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter }]

  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly) return
    try {
      await managedDelete(apiResourcePath('credentials', deleteTarget.id), managedRequestOptions(managedScope))
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const columns: Column<Secret>[] = [
    { key: 'id', header: t('managed.table.id'), render: (s) => <MonoId id={s.id} /> },
    { key: 'name', header: t('managed.table.name'), render: (s) => <span className="font-medium text-foreground">{s.name}</span> },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => <span className="text-xs text-muted-foreground"><RelativeTime date={s.created_at} /></span>,
    },
  ]

  if (list.isError)
    return (
      <ResourceErrorState
        error={list.error}
        resource="secret"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })}
      />
    )

  return (
    <div>
      {projectReadOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button size="sm" onClick={onCreate}>
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
      />
      <DataTable
        columns={columns}
        data={filtered}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(s) => router.push(`/managed/credentials/${s.id}`)}
        actionMenu={(s) =>
          projectReadOnly ? [] : [{ label: t('common.delete'), onClick: () => setDeleteTarget(s), destructive: true }]
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
        open={!projectReadOnly && Boolean(deleteTarget)}
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
