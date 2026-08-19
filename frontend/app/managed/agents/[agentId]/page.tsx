'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '@/lib/i18n'
import {
  Pencil,
  ChevronRight,
  Package,
  Globe,
  Play,
  Archive,
  ArchiveRestore,
  Trash2,
  Loader2,
} from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { toast } from '@/hooks/use-toast'
import { apiResourceId, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { VersionDiffView } from '@/components/managed/agent/version-diff-view'
import { AgentModelSummary } from '@/components/managed/agent/agent-model-summary'
import type { Agent, AgentTool, McpServer, Session } from '@/types/managed'
import { parseAgentId, parseSessionId } from '@/types/entity-id'
import { parseAgentResponse } from '@/lib/managed/agent-response-parsers'
import { parseSessionListResponse } from '@/lib/managed/session-response-parsers'
import { getSessionDisplayTitle } from '@/lib/managed/session-display'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import {
  PageHeader,
  StatusBadge,
  MonoId,
  RelativeTime,
  DataTable,
  type Column,
  FilterBar,
  ConfirmDialog,
  ResourceErrorState,
  withEntityRouteGuard,
} from '@/components/managed/shared'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface AgentVersion {
  version: number
  snapshot?: Agent
  created_at: string
}

interface DeletePreview {
  sessions: number
  tasks: number
  versions: number
  triggers: number
}

type PendingAction =
  | 'start'
  | 'archive'
  | 'restore'
  | 'delete-preview'
  | 'delete'
  | 'archive-session'

const ENGINE_KIND_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  claude_code: 'Claude Code',
  codex: 'Codex',
  native: 'Native',
}

export default withEntityRouteGuard(AgentDetailPageInner, {
  kind: 'agent',
  paramKey: 'agentId',
  backTo: '/managed/agents',
})

function AgentDetailPageInner({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId: rawAgentId } = React.use(params)
  const agentId = parseAgentId(rawAgentId)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const operationScope = `${managedScope.key}:${agentId ?? ''}`
  const actionRunRef = useRef(0)
  const pendingActionRef = useRef<PendingAction | null>(null)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const [showArchived, setShowArchived] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    title: string
    description: string
    confirmLabel: string
    destructive: boolean
    onConfirm: () => void
  }>({
    open: false,
    title: '',
    description: '',
    confirmLabel: '',
    destructive: false,
    onConfirm: () => {},
  })

  useEffect(() => {
    actionRunRef.current += 1
    pendingActionRef.current = null
    setPendingAction(null)
    operationScopeRef.current = operationScope
    managedRequestScopeRef.current = managedScope
    setConfirmDialog({
      open: false,
      title: '',
      description: '',
      confirmLabel: '',
      destructive: false,
      onConfirm: () => {},
    })
  }, [operationScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${agentId ?? ''}`
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId && currentOperationScopeIsActive(scope)

  const currentAgentIsActive = () => {
    if (!currentOperationScopeIsActive()) return false
    if (!currentProjectAllowsWrite()) return false
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    return !!currentAgent && currentAgent.id === agent?.id && !currentAgent.archived_at
  }

  const currentAgentIsWritable = () => {
    if (!currentOperationScopeIsActive()) return false
    if (!currentProjectAllowsWrite()) return false
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    return !!currentAgent && currentAgent.id === agent?.id
  }

  const nextAction = () => {
    if (!currentOperationScopeIsActive()) return null
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    return {
      runId,
      scope: operationScopeRef.current,
    }
  }

  const beginPendingAction = (type: PendingAction) => {
    if (pendingActionRef.current) return null
    const action = nextAction()
    if (!action) return null
    pendingActionRef.current = type
    setPendingAction(type)
    return action
  }

  const finishPendingAction = (runId: number, scope: string) => {
    if (!isCurrentAction(runId, scope)) return
    pendingActionRef.current = null
    setPendingAction(null)
  }

  const closeConfirmDialog = () => {
    actionRunRef.current += 1
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }

  const {
    data: agent,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['agent', managedScope.key, agentId],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('agents', agentId),
        managedRequestOptions(managedScope),
      ).then(parseAgentResponse),
    enabled: !!agentId && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })

  const { data: sessions } = useQuery({
    queryKey: ['agent-sessions', managedScope.key, agentId, showArchived],
    queryFn: async () => {
      const res = await managedGet<{ data: unknown[] }>(
        apiResourceSubpath('agents', agentId, ['sessions'], {
          include_archived: showArchived || undefined,
        }),
        managedRequestOptions(managedScope),
      )
      return parseSessionListResponse(res.data || [])
    },
    enabled: !!agentId && hasManagedRequestScope(managedScope),
  })

  const { data: versions } = useQuery({
    queryKey: ['agent-versions', managedScope.key, agentId],
    queryFn: async () => {
      const res = await managedGet<{ data: AgentVersion[] }>(
        apiResourcePath('agents', agentId, 'versions'),
        managedRequestOptions(managedScope),
      )
      return (res.data || []).map((version) => ({
        ...version,
        snapshot: version.snapshot ? parseAgentResponse(version.snapshot) : undefined,
      }))
    },
    enabled: !!agentId && hasManagedRequestScope(managedScope),
  })

  const handleStartSession = async () => {
    if (!currentAgentIsActive()) return

    const action = beginPendingAction('start')
    if (!action) return
    const { runId, scope: actionScope } = action
    const requestScope = managedRequestScopeRef.current
    if (!currentOperationScopeIsActive(actionScope)) return
    try {
      const res = await managedPost<{ id: string }>(
        '/sessions',
        { agent: apiResourceId(agentId) },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, actionScope)) return
      router.push(`/managed/sessions/${parseSessionId(res.id)}`)
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      finishPendingAction(runId, actionScope)
    }
  }

  const handleArchive = () => {
    if (!currentAgentIsActive()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.agents.archiveTitle'),
      description: t('managed.agents.archiveDescription', { name: agent?.name }),
      confirmLabel: t('common.archive'),
      destructive: false,
      onConfirm: async () => {
        if (!currentAgentIsActive()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = beginPendingAction('archive')
        if (!action) return
        const { runId, scope } = action
        const requestScope = managedRequestScopeRef.current
        setConfirmDialog((prev) => ({ ...prev, open: false }))
        try {
          await managedPost(
            apiResourcePath('agents', agentId, 'archive'),
            {},
            managedRequestOptions(requestScope),
          )
          if (!isCurrentAction(runId, scope)) return
          queryClient.invalidateQueries({ queryKey: ['agent', requestScope.key, agentId] })
          queryClient.invalidateQueries({ queryKey: ['agents', requestScope.key] })
          queryClient.invalidateQueries({
            queryKey: ['agent-sessions', requestScope.key, agentId],
            exact: false,
          })
          toast({ title: t('managed.agents.archiveSuccess', { name: agent?.name }) })
        } catch (e) {
          if (!isCurrentAction(runId, scope)) return
          toastOperationError(t, e, 'common.operationFailed')
        } finally {
          finishPendingAction(runId, scope)
        }
      },
    })
  }

  const handleRestore = () => {
    if (!currentAgentIsWritable()) return
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    if (!currentAgent?.archived_at) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.agents.restoreTitle'),
      description: t('managed.agents.restoreDescription', { name: agent?.name }),
      confirmLabel: t('common.restore'),
      destructive: false,
      onConfirm: async () => {
        const action = beginPendingAction('restore')
        if (!action) return
        const { runId, scope } = action
        const requestScope = managedRequestScopeRef.current
        setConfirmDialog((prev) => ({ ...prev, open: false }))
        try {
          await managedPost(
            apiResourcePath('agents', agentId, 'unarchive'),
            {},
            managedRequestOptions(requestScope),
          )
          if (!isCurrentAction(runId, scope)) return
          queryClient.invalidateQueries({ queryKey: ['agent', requestScope.key, agentId] })
          queryClient.invalidateQueries({ queryKey: ['agents', requestScope.key] })
          toast({ title: t('managed.agents.restoreSuccess', { name: agent?.name }) })
        } catch (e) {
          if (!isCurrentAction(runId, scope)) return
          toastOperationError(t, e, 'common.operationFailed')
        } finally {
          finishPendingAction(runId, scope)
        }
      },
    })
  }

  const handleDelete = async () => {
    if (!currentAgentIsWritable()) return

    const action = beginPendingAction('delete-preview')
    if (!action) return
    const { runId, scope } = action
    const requestScope = managedRequestScopeRef.current
    try {
      const preview = await managedGet<DeletePreview>(
        apiResourcePath('agents', agentId, 'delete_preview'),
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope) || !currentAgentIsWritable()) return
      const desc = t('managed.agents.deleteDescription', {
        name: agent?.name,
        sessions: preview.sessions,
        tasks: preview.tasks,
        versions: preview.versions,
        triggers: preview.triggers,
      })
      setConfirmDialog({
        open: true,
        title: t('managed.agents.deleteTitle', { name: agent?.name }),
        description: desc,
        confirmLabel: t('managed.agents.permanentlyDelete'),
        destructive: true,
        onConfirm: async () => {
          if (!currentAgentIsWritable()) {
            setConfirmDialog((prev) => ({ ...prev, open: false }))
            return
          }
          const action = beginPendingAction('delete')
          if (!action) return
          const requestScope = managedRequestScopeRef.current
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          try {
            await managedDelete(
              apiResourcePath('agents', agentId),
              managedRequestOptions(requestScope),
            )
            if (!isCurrentAction(action.runId, action.scope)) return
            queryClient.invalidateQueries({ queryKey: ['agents', requestScope.key] })
            toast({ title: t('managed.agents.deleteSuccess', { name: agent?.name }) })
            router.push('/managed/agents')
          } catch (e) {
            if (!isCurrentAction(action.runId, action.scope)) return
            toastOperationError(t, e, 'common.operationFailed')
          } finally {
            finishPendingAction(action.runId, action.scope)
          }
        },
      })
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      finishPendingAction(runId, scope)
    }
  }

  const handleArchiveSession = async (session: Session) => {
    if (!currentAgentIsActive()) return

    const currentSessions = queryClient.getQueryData<Session[]>([
      'agent-sessions',
      managedScope.key,
      agentId,
      showArchived,
    ])
    if (!currentSessions?.some((currentSession) => currentSession.id === session.id)) return

    const action = beginPendingAction('archive-session')
    if (!action) return
    const { runId, scope } = action
    const requestScope = managedRequestScopeRef.current
    try {
      await managedPost(
        apiResourcePath('sessions', session.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({
        queryKey: ['agent-sessions', requestScope.key, agentId],
        exact: false,
      })
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      finishPendingAction(runId, scope)
    }
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="agent"
        backLabel={t('managed.agents.backToAgents')}
        onBack={() => router.push('/managed/agents')}
      />
    )
  }

  if (isLoading || !agent) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!agent.archived_at
  const actionPending = pendingAction !== null
  const deletePending = pendingAction === 'delete-preview' || pendingAction === 'delete'

  return (
    <div>
      <PageHeader
        title={agent.name}
        titleExtra={<StatusBadge status={isArchived ? 'archived' : 'active'} />}
        breadcrumb={[
          { label: t('managed.agents.title'), to: '/managed/agents' },
          { label: agent.name },
        ]}
        action={
          <div className="flex items-center gap-2">
            {isArchived ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  onClick={handleRestore}
                >
                  {pendingAction === 'restore' ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ArchiveRestore className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t(pendingAction === 'restore' ? 'managed.agents.restoring' : 'common.restore')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  className="text-destructive hover:text-destructive"
                  onClick={handleDelete}
                >
                  {deletePending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t(
                    pendingAction === 'delete-preview'
                      ? 'managed.agents.preparingDelete'
                      : pendingAction === 'delete'
                        ? 'managed.agents.deleting'
                        : 'common.delete',
                  )}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="default"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  onClick={handleStartSession}
                >
                  {pendingAction === 'start' ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t(
                    pendingAction === 'start'
                      ? 'managed.agents.startingSession'
                      : 'managed.agents.startSession',
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  onClick={() => {
                    if (!currentAgentIsActive()) return
                    router.push(`/managed/agents/${agentId}/edit`)
                  }}
                >
                  <Pencil className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.edit')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  onClick={handleArchive}
                >
                  {pendingAction === 'archive' ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Archive className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t(pendingAction === 'archive' ? 'managed.agents.archiving' : 'common.archive')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly || actionPending}
                  className="text-destructive hover:text-destructive"
                  onClick={handleDelete}
                >
                  {deletePending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {t(
                    pendingAction === 'delete-preview'
                      ? 'managed.agents.preparingDelete'
                      : pendingAction === 'delete'
                        ? 'managed.agents.deleting'
                        : 'common.delete',
                  )}
                </Button>
              </>
            )}
          </div>
        }
      />

      <div className="mb-1 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={agent.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={agent.updated_at} />
      </div>
      {agent.description && (
        <p className="mb-4 mt-1 text-sm text-muted-foreground">{agent.description}</p>
      )}

      <Tabs defaultValue="agent" className="mt-4">
        <TabsList>
          <TabsTrigger value="agent">{t('managed.agents.tab.agent')}</TabsTrigger>
          <TabsTrigger value="sessions">{t('managed.agents.tab.sessions')}</TabsTrigger>
        </TabsList>

        <TabsContent value="agent">
          <AgentConfig agent={agent} versions={versions || []} />
        </TabsContent>

        <TabsContent value="sessions">
          <AgentSessions
            sessions={sessions || []}
            showArchived={showArchived}
            onArchivedChange={setShowArchived}
            onSelect={(s) => router.push(`/managed/sessions/${s.id}`)}
            onArchive={handleArchiveSession}
            canArchive={!projectReadOnly && !isArchived && !actionPending}
          />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        description={confirmDialog.description}
        confirmLabel={confirmDialog.confirmLabel}
        destructive={confirmDialog.destructive}
        onConfirm={confirmDialog.onConfirm}
        onCancel={closeConfirmDialog}
      />
    </div>
  )
}

function AgentConfig({ agent, versions: apiVersions }: { agent: Agent; versions: AgentVersion[] }) {
  const { t } = useTranslation()
  const currentVersion = agent.version || 1
  const [selectedVersion, setSelectedVersion] = useState<string>(String(currentVersion))
  const [compareMode, setCompareMode] = useState(false)
  const defaultBase = String(Math.max(1, currentVersion - 1))
  const [baseVersion, setBaseVersion] = useState<string>(defaultBase)
  const [targetVersion, setTargetVersion] = useState<string>(String(currentVersion))

  const allVersions: AgentVersion[] = (() => {
    const result: AgentVersion[] = []
    for (let i = currentVersion; i >= 1; i--) {
      const existing = apiVersions.find((v) => v.version === i)
      result.push(
        existing || { version: i, created_at: i === currentVersion ? agent.created_at : '' },
      )
    }
    return result
  })()

  const resolveAgent = (ver: number): Agent => {
    if (ver === currentVersion) return agent
    const entry = apiVersions.find((v) => v.version === ver)
    return entry ? (entry as AgentVersion & { snapshot?: Agent }).snapshot || agent : agent
  }

  const selectedAgent = resolveAgent(Number(selectedVersion))
  const baseAgent = resolveAgent(Number(baseVersion))
  const targetAgent = resolveAgent(Number(targetVersion))

  return (
    <div className="mt-4 space-y-6">
      {/* Version selector + compare toggle */}
      <section className="flex items-center gap-3">
        {compareMode ? (
          <>
            <Select value={baseVersion} onValueChange={setBaseVersion}>
              <SelectTrigger className="flex-1">
                <SelectValue>
                  {t('managed.agents.detail.baseVersion')}: v{baseVersion}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {allVersions.map((v) => (
                  <SelectItem key={v.version} value={String(v.version)}>
                    v{v.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={targetVersion} onValueChange={setTargetVersion}>
              <SelectTrigger className="flex-1">
                <SelectValue>
                  {t('managed.agents.detail.targetVersion')}: v{targetVersion}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {allVersions.map((v) => (
                  <SelectItem key={v.version} value={String(v.version)}>
                    v{v.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={() => setCompareMode(false)}>
              {t('managed.agents.detail.exitCompare')}
            </Button>
          </>
        ) : (
          <>
            <Select value={selectedVersion} onValueChange={setSelectedVersion}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={t('managed.agents.detail.selectVersion')}>
                  {t('managed.agents.detail.version')}: v{selectedVersion}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {allVersions.map((v) => (
                  <SelectItem key={v.version} value={String(v.version)}>
                    v{v.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {currentVersion > 1 && (
              <Button variant="outline" onClick={() => setCompareMode(true)}>
                {t('managed.agents.detail.compareMode')}
              </Button>
            )}
          </>
        )}
      </section>

      {compareMode ? (
        <VersionDiffView
          base={baseAgent}
          target={targetAgent}
          baseVersion={Number(baseVersion)}
          targetVersion={Number(targetVersion)}
        />
      ) : (
        <>
          {/* Engine */}
          <section>
            <h3 className="mb-1 text-sm font-medium text-foreground">
              {t('managed.agents.engineKind')}
            </h3>
            <p className="font-mono text-sm text-muted-foreground">
              {selectedAgent.engine_kind
                ? ENGINE_KIND_LABELS[selectedAgent.engine_kind] || selectedAgent.engine_kind
                : '-'}
            </p>
          </section>

          {/* Model */}
          <section>
            <h3 className="mb-1 text-sm font-medium text-foreground">
              {t('managed.modelDisplay.connection')}
            </h3>
            <AgentModelSummary agent={selectedAgent} detail />
          </section>

          {/* System prompt */}
          {selectedAgent.system && (
            <section>
              <h3 className="mb-2 text-sm font-medium text-foreground">
                {t('managed.agents.systemPrompt')}
              </h3>
              <div className="relative">
                <pre className="max-h-[300px] overflow-x-auto overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-4 font-mono text-xs">
                  {selectedAgent.system}
                </pre>
                <Button
                  variant="outline"
                  size="icon"
                  className="absolute right-2 top-2 h-7 w-7"
                  onClick={() => navigator.clipboard.writeText(selectedAgent.system || '')}
                  title={t('common.copyAll')}
                >
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                  </svg>
                </Button>
              </div>
            </section>
          )}

          {/* MCPs and tools */}
          <section>
            <h3 className="mb-3 text-sm font-medium text-foreground">
              {t('managed.agents.mcpAndTools')}
            </h3>
            <div className="space-y-3">
              {selectedAgent.tools &&
                selectedAgent.tools.map((tool, i) => (
                  <ToolCard key={i} tool={tool} mcpServers={selectedAgent.mcp_servers} />
                ))}
              {(!selectedAgent.tools || selectedAgent.tools.length === 0) && (
                <p className="text-sm text-muted-foreground">{t('managed.agents.noTools')}</p>
              )}
            </div>
          </section>

          {/* Skills */}
          <section>
            <h3 className="mb-1 text-sm font-medium text-foreground">
              {t('managed.agents.skills')}
            </h3>
            <p className="text-sm text-muted-foreground">
              {selectedAgent.skills && selectedAgent.skills.length > 0
                ? t('managed.agents.skillsCount', { count: selectedAgent.skills.length })
                : t('managed.agents.noSkills')}
            </p>
          </section>
        </>
      )}
    </div>
  )
}

function ToolCard({ tool, mcpServers }: { tool: AgentTool; mcpServers?: McpServer[] }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  if (tool.type === 'agent_toolset_20260401') {
    const configs = tool.configs || []
    const defaultPolicy = tool.default_config?.permission_policy?.type || 'always_allow'
    return (
      <div className="rounded-lg border border-border p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            <Package className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-medium">{t('managed.agents.builtInTools')}</div>
            <div className="font-mono text-xs text-muted-foreground">agent_toolset_20260401</div>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight
              className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
            />
            {t('managed.agents.toolPermissions')}
            {configs.length > 0 && (
              <Badge variant="outline" className="ml-1 px-1.5 py-0 text-[10px]">
                {configs.length}
              </Badge>
            )}
          </button>
          <span className="text-xs text-muted-foreground">{formatPolicy(defaultPolicy, t)}</span>
        </div>
        {expanded && configs.length > 0 && (
          <div className="ml-5 mt-2 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const enabled = cfg.enabled !== false
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between py-0.5 text-xs">
                  <span className="flex items-center gap-2">
                    {enabled ? (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded bg-emerald-500 text-white"
                        aria-label="enabled"
                      >
                        <svg
                          className="h-2.5 w-2.5"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={4}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    ) : (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded border border-border bg-background"
                        aria-label="disabled"
                      />
                    )}
                    <span
                      className={`font-mono ${enabled ? 'text-foreground' : 'text-muted-foreground line-through'}`}
                    >
                      {cfg.name}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">
                        ({t('managed.policy.inherit')})
                      </span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  if (tool.type === 'mcp_toolset') {
    const configs = tool.configs || []
    const serverName = tool.mcp_server_name
    const server = mcpServers?.find((s) => s.name === serverName)
    // Official Managed Agents default for mcp_toolset is always_ask when unset.
    const defaultPolicy = tool.default_config?.permission_policy?.type || 'always_ask'
    return (
      <div className="rounded-lg border border-border p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            <Globe className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-medium">{serverName}</div>
            {server && <div className="font-mono text-xs text-muted-foreground">{server.url}</div>}
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight
              className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
            />
            {t('managed.agents.toolPermissions')}
            {configs.length > 0 && (
              <Badge variant="outline" className="ml-1 px-1.5 py-0 text-[10px]">
                {configs.length}
              </Badge>
            )}
          </button>
          <span className="text-xs text-muted-foreground">{formatPolicy(defaultPolicy, t)}</span>
        </div>
        {expanded && configs.length > 0 && (
          <div className="ml-5 mt-2 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between py-0.5 text-xs">
                  <span className="font-mono text-foreground">{cfg.name}</span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">
                        ({t('managed.policy.inherit')})
                      </span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  if (tool.type === 'custom') {
    return (
      <div className="rounded-lg border border-border p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            <Package className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-medium">{tool.name}</div>
            <div className="text-xs text-muted-foreground">{tool.description}</div>
          </div>
        </div>
      </div>
    )
  }

  return null
}

function formatPolicy(policy: string, t: (key: string) => string): string {
  switch (policy) {
    case 'always_allow':
      return t('managed.policy.alwaysAllow')
    case 'always_ask':
      return t('managed.policy.alwaysAsk')
    case 'always_deny':
      return t('managed.policy.alwaysDeny')
    case 'ask':
      return t('managed.policy.ask')
    case 'inherit':
      return t('managed.policy.inherit')
    default:
      return policy.replace(/_/g, ' ')
  }
}

function AgentSessions({
  sessions,
  showArchived,
  onArchivedChange,
  onSelect,
  onArchive,
  canArchive,
}: {
  sessions: Session[]
  showArchived: boolean
  onArchivedChange: (v: boolean) => void
  onSelect: (s: Session) => void
  onArchive: (s: Session) => void
  canArchive: boolean
}) {
  const { t } = useTranslation()
  const [createdFilter, setCreatedFilter] = useState('all')
  const [versionFilter, setVersionFilter] = useState('all')
  const [page, setPage] = useState(0)
  const pageSize = 20

  const getCreatedCutoff = (filter: string): number => {
    const now = Date.now()
    switch (filter) {
      case '1h':
        return now - 60 * 60 * 1000
      case '24h':
        return now - 24 * 60 * 60 * 1000
      case '7d':
        return now - 7 * 24 * 60 * 60 * 1000
      default:
        return 0
    }
  }

  const filtered = sessions
    .filter((s) => showArchived || !s.archived_at)
    .filter((s) => {
      if (createdFilter === 'all') return true
      const cutoff = getCreatedCutoff(createdFilter)
      return new Date(s.created_at).getTime() >= cutoff
    })
    .filter((s) => {
      if (versionFilter === 'all') return true
      return String(s.agent?.version) === versionFilter
    })

  const paged = filtered.slice(page * pageSize, (page + 1) * pageSize)
  const hasNext = filtered.length > (page + 1) * pageSize
  const hasPrev = page > 0

  const versionOptions = Array.from(
    new Set(sessions.map((s) => s.agent?.version).filter(Boolean)),
  ).sort((a, b) => (b || 0) - (a || 0))

  const columns: Column<Session>[] = [
    { key: 'id', header: t('managed.table.id'), render: (s) => <MonoId id={s.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => (
        <span>{getSessionDisplayTitle(s.title, t('managed.sessions.untitledSession'))}</span>
      ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (s) => <StatusBadge status={s.status} />,
    },
    {
      key: 'version',
      header: t('managed.table.version'),
      render: (s) => (
        <span className="text-xs text-muted-foreground">v{s.agent?.version || '?'}</span>
      ),
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

  return (
    <div>
      <FilterBar
        showArchived={showArchived}
        onArchivedChange={onArchivedChange}
        filters={[
          {
            key: 'created',
            label: t('managed.filters.created'),
            value: createdFilter,
            onChange: (v) => {
              setCreatedFilter(v)
              setPage(0)
            },
            options: [
              { value: 'all', label: t('managed.filters.allTime') },
              { value: '1h', label: t('managed.filters.lastHour') },
              { value: '24h', label: t('managed.filters.last24h') },
              { value: '7d', label: t('managed.filters.last7d') },
            ],
          },
          {
            key: 'version',
            label: t('managed.filters.version'),
            value: versionFilter,
            onChange: (v) => {
              setVersionFilter(v)
              setPage(0)
            },
            options: [
              { value: 'all', label: t('managed.filters.all') },
              ...versionOptions.map((v) => ({ value: String(v), label: `v${v}` })),
            ],
          },
        ]}
      />
      <DataTable
        columns={columns}
        data={paged}
        onRowClick={onSelect}
        selectable
        actionMenu={(s) => [
          { label: t('managed.agents.viewDetails'), onClick: () => onSelect(s) },
          ...(s.archived_at || !canArchive
            ? []
            : [{ label: t('common.archive'), onClick: () => onArchive(s), destructive: false }]),
        ]}
        pagination={{
          hasNext,
          hasPrev,
          onNext: () => setPage((p) => p + 1),
          onPrev: () => setPage((p) => p - 1),
        }}
        emptyMessage={t('managed.agents.noSessions')}
      />
    </div>
  )
}
