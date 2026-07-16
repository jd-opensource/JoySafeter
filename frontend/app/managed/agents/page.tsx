'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
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
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface DeletePreview {
  sessions: number
  tasks: number
  versions: number
}

export default function AgentListPage() {
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

  useEffect(() => {
    if (managedScopeRef.current !== managedScope) {
      actionRunRef.current += 1
      setDeleteTarget(null)
      setDeletePreview(null)
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
    setDeleteTarget(null)
    setDeletePreview(null)
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

  const currentAgentIsActive = (agent: Agent, scope: string) =>
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: Agent[] }>({ queryKey: ['agents', scope, '/agents'] })
      .some(([, page]) =>
        page?.data?.some((currentAgent) => currentAgent.id === agent.id && !currentAgent.archived_at),
      )

  const handleDeleteClick = async (agent: Agent) => {
    if (!currentProjectAllowsWrite()) return
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    if (!currentAgentIsActive(agent, actionScope)) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    try {
      const rawId = stripIdPrefix(agent.id)
      const preview = await managedGet<DeletePreview>(`/agents/${rawId}/delete_preview`)
      if (!isCurrentAction(runId, actionScope)) return
      setDeletePreview(preview)
      setDeleteTarget(agent)
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
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
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    if (!currentAgentIsActive(deleteTarget, actionScope)) {
      setDeleteTarget(null)
      setDeletePreview(null)
      return
    }

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    try {
      const rawId = stripIdPrefix(deleteTarget.id)
      await managedDelete(`/agents/${rawId}`)
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, actionScope)) {
        setDeleteTarget(null)
        setDeletePreview(null)
      }
    }
  }

  const handleArchive = async (agent: Agent) => {
    if (!currentProjectAllowsWrite()) return
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    if (!currentAgentIsActive(agent, actionScope)) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    try {
      await managedPost(`/agents/${stripIdPrefix(agent.id)}/archive`, {})
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
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
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['agents'] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.agents.title')}
        subtitle={t('managed.agents.subtitle')}
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
          projectReadOnly || a.archived_at
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
        open={!projectReadOnly && !!deleteTarget}
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
        open={!projectReadOnly && showCreateDialog}
        onOpenChange={(open) => {
          if (open && !currentProjectAllowsWrite()) return
          setShowCreateDialog(open)
        }}
        onCreated={(id) => {
          queryClient.invalidateQueries({ queryKey: ['agents'] })
          router.push(`/managed/agents/${id}`)
        }}
      />
    </div>
  )
}
