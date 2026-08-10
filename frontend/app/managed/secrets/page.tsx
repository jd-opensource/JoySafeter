'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Check, Plus, Star } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'

import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  PageHeader,
  RelativeTime,
  ResourceErrorState,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
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
import { parseSecretId } from '@/types/entity-id'
import type { Secret, SecretDetail } from '@/types/managed'

import { CreateSecretDialog } from './components/create-secret-dialog'

function displayId(value: string | null) {
  if (!value) return '—'
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export default function SecretListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [initialKind, setInitialKind] = useState<'llm' | 'generic'>('llm')
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const list = usePaginatedList<Secret>({
    queryKey: 'secrets',
    path: '/secrets',
    cacheVersion: catalogVersion || undefined,
    enabled: catalogReady,
    parseItem: parseSecretResponse,
    parseCursor: parseSecretId,
  })

  useEffect(() => {
    const create = searchParams.get('create')
    if (create !== 'llm' && create !== 'generic' && create !== 'custom') return
    setInitialKind(create === 'llm' ? 'llm' : 'generic')
    setShowCreate(true)
    router.replace('/managed/secrets')
  }, [router, searchParams])

  const filteredSecrets = useMemo(
    () =>
      list.data.filter(
        (secret) =>
          filterByCreatedTime(secret.created_at, createdFilter) &&
          matchesSearch(searchQuery, [
            secret.id,
            secret.name,
            secret.kind,
            secret.provider ?? '',
            secret.protocol ?? '',
            secret.model ?? '',
          ]),
      ),
    [createdFilter, list.data, searchQuery],
  )

  const filters: FilterDef[] = [
    { ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter },
  ]

  const invalidateSecretQueries = () => {
    queryClient.invalidateQueries({ queryKey: ['secrets', managedScope.key] })
    queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
  }

  const handleSetDefault = async (secret: Secret) => {
    if (secret.kind !== 'llm' || projectReadOnly) return
    try {
      await managedPost(
        apiResourcePath('secrets', secret.id, 'default'),
        {},
        managedRequestOptions(managedScope),
      )
      invalidateSecretQueries()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly) return
    try {
      await managedDelete(
        apiResourcePath('secrets', deleteTarget.id),
        managedRequestOptions(managedScope),
      )
      invalidateSecretQueries()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const columns: Column<Secret>[] = [
    { key: 'id', header: t('managed.table.id'), render: (secret) => <MonoId id={secret.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (secret) => (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{secret.name}</span>
            {secret.is_default ? (
              <Badge variant="secondary" className="gap-1">
                <Check className="h-3 w-3" />
                {t('managed.secrets.default')}
              </Badge>
            ) : null}
          </div>
          {secret.model ? <p className="text-xs text-muted-foreground">{secret.model}</p> : null}
        </div>
      ),
    },
    {
      key: 'kind',
      header: t('managed.llm.configurationType'),
      render: (secret) => (
        <Badge variant={secret.kind === 'llm' ? 'default' : 'outline'}>
          {secret.kind === 'llm'
            ? t('managed.llm.modelConfiguration')
            : t('managed.llm.genericSecret')}
        </Badge>
      ),
    },
    {
      key: 'binding',
      header: t('managed.llm.providerProtocol'),
      render: (secret) =>
        secret.kind === 'llm' ? (
          <div className="text-xs">
            <p className="font-medium text-foreground">{displayId(secret.provider)}</p>
            <p className="text-muted-foreground">{displayId(secret.protocol)}</p>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'engines',
      header: t('managed.llm.compatibleEngines'),
      render: (secret) => (
        <CompatibleEngineBadges
          engineIds={secret.compatible_engine_ids}
          catalog={catalogQuery.data}
        />
      ),
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (secret) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={secret.created_at} />
        </span>
      ),
    },
  ]

  if (catalogQuery.isError) {
    return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  }
  if (!catalogReady) {
    return <LlmCatalogPageState state="loading" />
  }
  if (list.isError) {
    return (
      <ResourceErrorState
        error={list.error}
        resource="secret"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['secrets', managedScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.secrets.title')}
        subtitle={t('managed.secrets.subtitle')}
        action={
          projectReadOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                setInitialKind('llm')
                setShowCreate(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.secrets.new')}
            </Button>
          )
        }
      />
      <FilterBar
        searchPlaceholder={t('managed.search.secrets')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />
      <DataTable
        columns={columns}
        data={filteredSecrets}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(secret) => router.push(`/managed/secrets/${secret.id}`)}
        actionMenu={(secret) =>
          projectReadOnly
            ? []
            : [
                ...(secret.kind === 'llm' && !secret.is_default
                  ? [
                      {
                        label: t('managed.secrets.setDefault'),
                        icon: <Star className="h-4 w-4" />,
                        onClick: () => handleSetDefault(secret),
                      },
                    ]
                  : []),
                {
                  label: t('common.delete'),
                  onClick: () => setDeleteTarget(secret),
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
        emptyMessage={t('managed.secrets.empty')}
      />

      <CreateSecretDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        initialKind={initialKind}
        onCreated={(_secret: SecretDetail) => {
          setShowCreate(false)
          invalidateSecretQueries()
        }}
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
