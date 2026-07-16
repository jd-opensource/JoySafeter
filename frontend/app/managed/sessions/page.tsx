'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
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
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

export default function SessionListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const actionRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope)
  const [showArchived, setShowArchived] = useState(false)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [agentFilter, setAgentFilter] = useState('all')
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
  } = usePaginatedList<Session>({
    queryKey: 'sessions',
    path: '/sessions',
    includeArchived: showArchived,
  })

  const getEngineKindLabel = (engineKind?: string | null) => {
    switch (engineKind) {
      case 'claude':
      case 'claude_code':
        return 'Claude Code'
      case 'codex':
        return 'Codex'
      case 'native':
        return 'Native'
      default:
        return engineKind || '-'
    }
  }

  const sessions = data.filter(
    (s) =>
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
      render: (s) => <span className="text-foreground">{s.title || '-'}</span>,
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
        <span className="whitespace-nowrap text-muted-foreground">
          {getEngineKindLabel(s.agent?.engine_kind)}
        </span>
      ),
    },
    {
      key: 'agent',
      header: t('managed.table.agent'),
      render: (s) => <span className="text-xs text-muted-foreground">{s.agent?.name || '-'}</span>,
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

  useEffect(() => {
    if (!projectReadOnly) return
    actionRunRef.current += 1
    setShowCreateDialog(false)
  }, [projectReadOnly])

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    managedScopeRef.current === scope &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const handleArchive = async (session: Session) => {
    if (!currentProjectAllowsWrite()) return
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    const sessionStillCurrent = queryClient
      .getQueriesData<{ data?: Session[] }>({ queryKey: ['sessions', actionScope, '/sessions'] })
      .some(([, page]) => page?.data?.some((currentSession) => currentSession.id === session.id))
    if (!sessionStillCurrent) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    try {
      await managedPost(`/sessions/${stripIdPrefix(session.id)}/archive`, {})
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="session"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['sessions'] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.sessions.title')}
        subtitle={t('managed.sessions.subtitle')}
        action={
          projectReadOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                if (!currentProjectAllowsWrite()) return
                setShowCreateDialog(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.sessions.new')}
            </Button>
          )
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
        actionMenu={(s) =>
          projectReadOnly || s.archived_at
            ? []
            : [
                {
                  label: t('managed.sessions.archiveSession'),
                  onClick: () => handleArchive(s),
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
        emptyMessage={t('managed.sessions.empty')}
      />

      <CreateSessionDialog
        open={!projectReadOnly && showCreateDialog}
        onOpenChange={(open) => {
          if (open && !currentProjectAllowsWrite()) return
          setShowCreateDialog(open)
        }}
        onCreated={(id) => {
          queryClient.invalidateQueries({ queryKey: ['sessions'] })
          router.push(`/managed/sessions/${id}`)
        }}
      />
    </div>
  )
}
