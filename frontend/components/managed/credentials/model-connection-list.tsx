'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Check, Plus, Star } from 'lucide-react'
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
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretResponse } from '@/lib/managed/secret-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Secret } from '@/types/managed'

function displayId(value: string | null) {
  if (!value) return '—'
  return value.split('_').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
}

export function ModelConnectionList({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const list = usePaginatedList<Secret>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'model' },
    cacheVersion: catalogVersion || undefined,
    enabled: catalogReady,
    parseItem: parseSecretResponse,
    parseCursor: parseCredentialId,
  })

  const filtered = useMemo(
    () =>
      list.data.filter(
        (s) =>
          filterByCreatedTime(s.created_at, createdFilter) &&
          matchesSearch(searchQuery, [s.id, s.name, s.provider ?? '', s.protocol ?? '', s.model ?? '']),
      ),
    [createdFilter, list.data, searchQuery],
  )
  const filters: FilterDef[] = [{ ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter }]

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
  }
  const handleSetDefault = async (s: Secret) => {
    if (s.kind !== 'model' || projectReadOnly) return
    try {
      await managedPost(apiResourcePath('credentials', s.id, 'default'), {}, managedRequestOptions(managedScope))
      invalidate()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    }
  }
  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly) return
    try {
      await managedDelete(apiResourcePath('credentials', deleteTarget.id), managedRequestOptions(managedScope))
      invalidate()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
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
      render: (s) => <CompatibleEngineBadges engineIds={s.compatible_engine_ids} catalog={catalogQuery.data} />,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => <span className="text-xs text-muted-foreground"><RelativeTime date={s.created_at} /></span>,
    },
  ]

  if (catalogQuery.isError) return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  if (!catalogReady) return <LlmCatalogPageState state="loading" />
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
            {t('managed.credentials.addModelConnection')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.credentials.searchModelsOnPage')}
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
          projectReadOnly
            ? []
            : [
                ...(s.kind === 'model' && !s.is_default
                  ? [{ label: t('managed.secrets.setDefault'), icon: <Star className="h-4 w-4" />, onClick: () => handleSetDefault(s) }]
                  : []),
                { label: t('common.delete'), onClick: () => setDeleteTarget(s), destructive: true },
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
