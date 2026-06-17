'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Plus } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedPost } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'
import type { Session } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/managed/shared'
import { FilterBar, type FilterDef } from '@/components/managed/shared'
import { DataTable, type Column } from '@/components/managed/shared'
import { StatusBadge } from '@/components/managed/shared'
import { MonoId } from '@/components/managed/shared'
import { RelativeTime } from '@/components/managed/shared'
import { ResourceErrorState } from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { toastOperationError } from '@/lib/managed/errors'
import { CreateSessionDialog } from './components/create-session-dialog'

export default function SessionListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [agentFilter, setAgentFilter] = useState('all')
  const [createdFilter, setCreatedFilter] = useState('all')

  const { data, isLoading, isFetching, isError, error, hasNext, hasPrev, page, pageSize, pageSizeOptions, goNext, goPrev, goToPage, setPageSize } =
    usePaginatedList<Session>({ queryKey: 'sessions', path: '/sessions', includeArchived: showArchived })

  const getEngineKindLabel = (engineKind?: string | null) => {
    switch (engineKind) {
      case 'claude':
      case 'claude_code':
        return 'Claude Code'
      case 'codex':
        return 'Codex'
      case 'native':
        return 'Native'
      case 'langgraph_visual':
        return 'LangGraph Visual'
      case 'langgraph_code':
        return 'LangGraph Code'
      default:
        return engineKind || '-'
    }
  }

  const sessions = data.filter((s) =>
    filterByCreatedTime(s.created_at, createdFilter) &&
    matchesSearch(searchQuery, [
      s.id,
      s.title,
      s.status,
      s.agent?.name,
      s.agent?.id,
      s.agent?.engine_kind,
      getEngineKindLabel(s.agent?.engine_kind),
    ]),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
    {
      key: 'agent',
      label: t('managed.filters.agent'),
      value: agentFilter,
      onChange: setAgentFilter,
      options: [{ value: 'all', label: t('managed.filters.all') }],
    },
  ]

  const columns: Column<Session>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (s) => <MonoId id={s.id} />,
    },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => (
        <span className="text-foreground">{s.title || '-'}</span>
      ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (s) => <StatusBadge status={s.status} />,
    },
    {
      key: 'engine_kind',
      header: t('managed.table.engineKind'),
      render: (s) => (
        <span className="text-muted-foreground whitespace-nowrap">
          {getEngineKindLabel(s.agent?.engine_kind)}
        </span>
      ),
    },
    {
      key: 'agent',
      header: t('managed.table.agent'),
      render: (s) => (
        <span className="text-muted-foreground text-xs">
          {s.agent?.name || '-'}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => (
        <span className="text-muted-foreground text-xs">
          <RelativeTime date={s.created_at} />
        </span>
      ),
    },
  ]

  if (isError) {
    return <ResourceErrorState error={error} resource="session" onRetry={() => queryClient.invalidateQueries({ queryKey: ['sessions'] })} />
  }

  return (
    <div>
      <PageHeader
        title={t('managed.sessions.title')}
        subtitle={t('managed.sessions.subtitle')}
        action={
          <Button size="sm" onClick={() => setShowCreateDialog(true)}>
            <Plus className="w-4 h-4" />
            {t('managed.sessions.new')}
          </Button>
        }
      />

      <FilterBar
        searchPlaceholder={t('managed.search.sessions')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        onSearch={(id) => router.push(`/managed/sessions/${id}`)}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />

      <DataTable
        columns={columns}
        data={sessions}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(s) => router.push(`/managed/sessions/${s.id}`)}
        actionMenu={(s) => s.archived_at ? [] : [
          {
            label: t('managed.sessions.archiveSession'),
            onClick: async () => {
              try {
                await managedPost(`/sessions/${stripIdPrefix(s.id)}/archive`, {})
                queryClient.invalidateQueries({ queryKey: ['sessions'] })
              } catch (e) {
                toastOperationError(t, e, 'common.operationFailed')
              }
            },
          },
        ]}
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
        emptyMessage={t('managed.sessions.empty')}
      />

      <CreateSessionDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onCreated={(id) => {
          queryClient.invalidateQueries({ queryKey: ['sessions'] })
          router.push(`/managed/sessions/${id}`)
        }}
      />
    </div>
  )
}
