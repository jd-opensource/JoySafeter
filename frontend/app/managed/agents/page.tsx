'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, ArrowRight, Loader2, Pencil, Play, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { AgentModelSummary } from '@/components/managed/agent/agent-model-summary'
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
  ActionMenu,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { ToastAction } from '@/components/ui/toast'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { toast } from '@/hooks/use-toast'
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { getAgentModelSearchTokens } from '@/lib/managed/agent-model-display'
import { parseAgentResponse } from '@/lib/managed/agent-response-parsers'
import { apiResourceId, apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { isEntityId, parseAgentId, parseSessionId } from '@/types/entity-id'
import type { Agent } from '@/types/managed'

import { CreateAgentDialog } from './components/create-agent-dialog'

interface LifecycleConfirm {
  agent: Agent
  action: 'archive' | 'restore'
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
  } = useScopedActions({
    onReset: () => {
      setLifecycleConfirm(null)
      setPendingAction(null)
      setShowCreateDialog(false)
    },
  })
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [lifecycleConfirm, setLifecycleConfirm] = useState<LifecycleConfirm | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [pendingAction, setPendingAction] = useState<{
    agentId: Agent['id']
    type: 'start' | 'archive' | 'restore'
  } | null>(null)

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
    parseItem: parseAgentResponse,
    parseCursor: parseAgentId,
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
      case 'pi':
        return 'Pi'
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
        ...getAgentModelSearchTokens(a),
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

  const currentAgentIsArchived = (agent: Agent, scope: string) =>
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: Agent[] }>({ queryKey: ['agents', scope, '/agents'] })
      .some(([, page]) =>
        page?.data?.some(
          (currentAgent) => currentAgent.id === agent.id && !!currentAgent.archived_at,
        ),
      )

  const handleArchiveConfirm = async () => {
    const target = lifecycleConfirm?.action === 'archive' ? lifecycleConfirm.agent : null
    if (!target) return
    if (!currentAgentIsActive(target, managedScopeRef.current)) {
      setLifecycleConfirm(null)
      return
    }

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    setLifecycleConfirm(null)
    setPendingAction({ agentId: target.id, type: 'archive' })
    try {
      await managedPost(
        apiResourcePath('agents', target.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agents', scope] })
      toast({
        title: t('managed.agents.archiveSuccess', { name: target.name }),
        action: (
          <ToastAction altText={t('common.undo')} onClick={() => handleUndoArchive(target, scope)}>
            {t('common.undo')}
          </ToastAction>
        ),
      })
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, scope)) setPendingAction(null)
    }
  }

  const handleUndoArchive = async (agent: Agent, archivedScope: string) => {
    if (!currentProjectAllowsWrite()) return
    if (!scopeIsActive(archivedScope)) return

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    setPendingAction({ agentId: agent.id, type: 'restore' })
    try {
      await managedPost(
        apiResourcePath('agents', agent.id, 'unarchive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agents', scope] })
      toast({ title: t('managed.agents.restoreSuccess', { name: agent.name }) })
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, scope)) setPendingAction(null)
    }
  }

  const handleStartSession = async (agent: Agent) => {
    if (!currentAgentIsActive(agent, managedScopeRef.current)) return

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    setPendingAction({ agentId: agent.id, type: 'start' })
    try {
      const response = await managedPost<{ id: string }>(
        '/sessions',
        { agent: apiResourceId(agent.id) },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      router.push(`/managed/sessions/${parseSessionId(response.id)}`)
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, scope)) setPendingAction(null)
    }
  }

  const handleRestoreConfirm = async () => {
    const target = lifecycleConfirm?.action === 'restore' ? lifecycleConfirm.agent : null
    if (!target) return
    if (!currentAgentIsArchived(target, managedScopeRef.current)) {
      setLifecycleConfirm(null)
      return
    }

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    setLifecycleConfirm(null)
    setPendingAction({ agentId: target.id, type: 'restore' })
    try {
      await managedPost(
        apiResourcePath('agents', target.id, 'unarchive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agents', scope] })
      toast({ title: t('managed.agents.restoreSuccess', { name: target.name }) })
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(runId, scope)) setPendingAction(null)
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
      render: (a) => (
        <button
          type="button"
          className="group inline-flex max-w-full items-center gap-1 font-medium text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          onClick={(event) => {
            event.stopPropagation()
            router.push(`/managed/agents/${a.id}`)
          }}
        >
          <span className="truncate">{a.name}</span>
          <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
        </button>
      ),
    },
    {
      key: 'model_connection',
      header: `${t('managed.modelDisplay.connection')} / ${t('managed.agents.engineKind')}`,
      render: (a) => (
        <div className="min-w-0">
          <AgentModelSummary agent={a} />
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {t('managed.agents.engineKind')}: {getEngineKindLabel(a.engine_kind)}
          </div>
        </div>
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
    {
      key: 'actions',
      header: t('managed.table.actions'),
      width: '270px',
      align: 'right',
      truncate: false,
      cellClassName: 'overflow-visible',
      render: (a) => {
        const isStarting = pendingAction?.agentId === a.id && pendingAction.type === 'start'
        const isArchiving = pendingAction?.agentId === a.id && pendingAction.type === 'archive'
        const isRestoring = pendingAction?.agentId === a.id && pendingAction.type === 'restore'
        const rowIsPending = pendingAction?.agentId === a.id
        return (
          <div
            className="flex items-center justify-end gap-1"
            onClick={(event) => event.stopPropagation()}
          >
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push(`/managed/agents/${a.id}`)}
            >
              {t('managed.agents.viewDetails')}
            </Button>
            {!readOnly && !a.archived_at && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={rowIsPending}
                  onClick={() => handleStartSession(a)}
                >
                  {isStarting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  {t(isStarting ? 'managed.agents.startingSession' : 'managed.agents.startSession')}
                </Button>
                {isArchiving ? (
                  <Button variant="outline" size="sm" disabled>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {t('managed.agents.archiving')}
                  </Button>
                ) : (
                  <ActionMenu
                    disabled={rowIsPending}
                    ariaLabel={t('managed.agents.moreActions', { name: a.name })}
                    items={[
                      {
                        label: t('common.edit'),
                        icon: <Pencil className="h-3.5 w-3.5" />,
                        onClick: () => router.push(`/managed/agents/${a.id}/edit`),
                      },
                      {
                        label: t('common.archive'),
                        icon: <Archive className="h-3.5 w-3.5" />,
                        separator: true,
                        onClick: () => setLifecycleConfirm({ agent: a, action: 'archive' }),
                      },
                    ]}
                  />
                )}
              </>
            )}
            {!readOnly && a.archived_at && (
              <Button
                variant="outline"
                size="sm"
                disabled={rowIsPending}
                onClick={() => setLifecycleConfirm({ agent: a, action: 'restore' })}
              >
                {isRestoring ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ArchiveRestore className="h-3.5 w-3.5" />
                )}
                {t(isRestoring ? 'managed.agents.restoring' : 'common.restore')}
              </Button>
            )}
          </div>
        )
      },
    },
  ]

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
        onSearch={(value) => {
          if (isEntityId(value, 'agent')) router.push(`/managed/agents/${value}`)
        }}
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
        open={!readOnly && lifecycleConfirm?.action === 'archive'}
        title={t('managed.agents.archiveTitle')}
        description={t('managed.agents.archiveDescription', {
          name: lifecycleConfirm?.agent.name,
        })}
        confirmLabel={t('common.archive')}
        onConfirm={handleArchiveConfirm}
        onCancel={() => setLifecycleConfirm(null)}
      />

      <ConfirmDialog
        open={!readOnly && lifecycleConfirm?.action === 'restore'}
        title={t('managed.agents.restoreTitle')}
        description={t('managed.agents.restoreDescription', {
          name: lifecycleConfirm?.agent.name,
        })}
        confirmLabel={t('common.restore')}
        onConfirm={handleRestoreConfirm}
        onCancel={() => setLifecycleConfirm(null)}
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
