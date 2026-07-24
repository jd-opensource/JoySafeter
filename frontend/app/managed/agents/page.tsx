'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import type { Agent } from '@/types/managed'
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
import { CreateAgentDialog } from './components/create-agent-dialog'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'

interface DeletePreview {
  sessions: number
  tasks: number
  versions: number
}

export default function AgentListPage() {
  const { t } = useTranslation()
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
      setDeleteTarget(null)
      setDeletePreview(null)
      setShowCreateDialog(false)
    },
  })
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [deleteTarget, setDeleteTarget] = useState<Agent | null>(null)
  const [deletePreview, setDeletePreview] = useState<DeletePreview | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)

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
  } = usePaginatedList<Agent>({
    queryKey: 'agents',
    path: '/agents',
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

  const agents = data.filter(
    (a) =>
      filterByCreatedTime(a.created_at, createdFilter) &&
      matchesSearch(searchQuery, [
        a.id,
        a.name,
        a.model?.id,
        a.engine_kind,
        getEngineKindLabel(a.engine_kind),
        a.archived_at ? 'archived' : 'active',
      ]),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  const currentAgentIsActive = (agent: Agent, scope: string) =>
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: Agent[] }>({ queryKey: ['agents', scope, '/agents'] })
      .some(([, page]) =>
        page?.data?.some(
          (currentAgent) => currentAgent.id === agent.id && !currentAgent.archived_at,
        ),
      )

  const handleDeleteClick = async (agent: Agent) => {
    if (!currentProjectAllowsWrite()) return
    if (!scopeIsActive()) return
    if (!currentAgentIsActive(agent, managedScopeRef.current)) return

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    try {
      const preview = await managedGet<DeletePreview>(
        apiResourcePath('agents', agent.id, 'delete_preview'),
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      setDeletePreview(preview)
      setDeleteTarget(agent)
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    if (!currentProjectAllowsWrite()) {
      setDeleteTarget(null)
      setDeletePreview(null)
      return
    }
    if (!scopeIsActive()) return
    if (!currentAgentIsActive(deleteTarget, managedScopeRef.current)) {
      setDeleteTarget(null)
      setDeletePreview(null)
      return
    }

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    try {
      await managedDelete(
        apiResourcePath('agents', deleteTarget.id),
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agents', scope] })
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, scope)) {
        setDeleteTarget(null)
        setDeletePreview(null)
      }
    }
  }

  const handleArchive = async (agent: Agent) => {
    if (!currentProjectAllowsWrite()) return
    if (!scopeIsActive()) return
    if (!currentAgentIsActive(agent, managedScopeRef.current)) return

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    try {
      await managedPost(
        apiResourcePath('agents', agent.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agents', scope] })
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const columns: Column<Agent>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (a) => <MonoId id={a.id} />,
    },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (a) => <span className="font-medium text-foreground">{a.name}</span>,
    },
    {
      key: 'model',
      header: t('managed.table.model'),
      render: (a) => <span className="text-muted-foreground">{a.model?.id || '-'}</span>,
    },
    {
      key: 'engine_kind',
      header: t('managed.table.engineKind'),
      render: (a) => (
        <span className="whitespace-nowrap text-muted-foreground">
          {getEngineKindLabel(a.engine_kind)}
        </span>
      ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (a) => <StatusBadge status={a.archived_at ? 'archived' : 'active'} />,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (a) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={a.created_at} />
        </span>
      ),
    },
    {
      key: 'updated_at',
      header: t('managed.table.lastUpdated'),
      render: (a) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={a.updated_at} />
        </span>
      ),
    },
  ]

  const buildDeleteDescription = () => {
    if (!deleteTarget || !deletePreview) return ''
    const lines: string[] = []
    if (deletePreview.sessions > 0) {
      lines.push(`  • ${t('managed.agents.deleteSessions', { count: deletePreview.sessions })}`)
    }
    if (deletePreview.tasks > 0) {
      lines.push(`  • ${t('managed.agents.deleteTasks', { count: deletePreview.tasks })}`)
    }
    if (deletePreview.versions > 0) {
      lines.push(`  • ${t('managed.agents.deleteVersions', { count: deletePreview.versions })}`)
    }
    if (lines.length > 0) {
      return t('managed.agents.deleteHasData', { details: lines.join('\n') })
    }
    return t('managed.agents.deleteNoData')
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="agent"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['agents', managedScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.agents.title')}
        subtitle={t('managed.agents.subtitle')}
        action={
          readOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                if (!currentProjectAllowsWrite()) return
                if (!scopeIsActive()) return
                setShowCreateDialog(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.agents.new')}
            </Button>
          )
        }
      />
      <FilterBar
        searchPlaceholder={t('managed.search.agents')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        onSearch={(id) => router.push(`/managed/agents/${id}`)}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />

      <DataTable
        columns={columns}
        data={agents}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(a) => router.push(`/managed/agents/${a.id}`)}
        actionMenu={(a) =>
          readOnly || a.archived_at
            ? []
            : [
                {
                  label: t('managed.agents.archiveAgent'),
                  onClick: () => handleArchive(a),
                },
                {
                  label: t('common.delete'),
                  destructive: true,
                  icon: <Trash2 className="h-3.5 w-3.5" />,
                  onClick: () => handleDeleteClick(a),
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
        emptyMessage={t('managed.agents.empty')}
      />

      <ConfirmDialog
        open={!readOnly && !!deleteTarget}
        title={t('managed.agents.deleteTitle', { name: deleteTarget?.name })}
        description={buildDeleteDescription()}
        confirmLabel={t('managed.agents.permanentlyDelete')}
        destructive
        onConfirm={handleDeleteConfirm}
        onCancel={() => {
          setDeleteTarget(null)
          setDeletePreview(null)
        }}
      />

      <CreateAgentDialog
        open={!readOnly && showCreateDialog}
        onOpenChange={(open) => {
          if (open && !currentProjectAllowsWrite()) return
          if (open && !scopeIsActive()) return
          setShowCreateDialog(open)
        }}
        onCreated={(id) => {
          const scope = managedScopeRef.current
          if (!scopeIsActive(scope)) return
          queryClient.invalidateQueries({ queryKey: ['agents', scope] })
          router.push(`/managed/agents/${id}`)
        }}
      />
    </div>
  )
}
