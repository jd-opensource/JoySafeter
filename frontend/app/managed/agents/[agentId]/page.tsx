'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '@/lib/i18n'
import { Pencil, ChevronRight, Package, Globe, Play, Sparkles, Archive } from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { VersionDiffView } from '@/components/managed/agent/version-diff-view'
import type { Agent, AgentTool, McpServer, PaginatedResponse, Session } from '@/types/managed'
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
  ActionMenu,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'

interface AgentVersion {
  version: number
  snapshot?: Agent
  created_at: string
}

interface DeletePreview {
  sessions: number
  tasks: number
  versions: number
}

const ENGINE_KIND_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  claude_code: 'Claude Code',
  codex: 'Codex',
  native: 'Native',
}

export default function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
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

  const {
    data: agent,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => managedGet<Agent>(`/agents/${stripIdPrefix(agentId)}`),
    enabled: !!agentId,
    retry: shouldRetryManagedResourceError,
  })

  const { data: sessions } = useQuery({
    queryKey: ['agent-sessions', agentId, showArchived],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Session>>(
        `/agents/${stripIdPrefix(agentId)}/sessions${showArchived ? '?include_archived=true' : ''}`,
      )
      return res.data || []
    },
    enabled: !!agentId,
  })

  const { data: versions } = useQuery({
    queryKey: ['agent-versions', agentId],
    queryFn: async () => {
      const res = await managedGet<{ data: AgentVersion[] }>(
        `/agents/${stripIdPrefix(agentId)}/versions`,
      )
      return res.data || []
    },
    enabled: !!agentId,
  })

  const handleStartSession = async () => {
    try {
      const res = await managedPost<{ id: string }>('/sessions', { agent: agentId })
      router.push(`/managed/sessions/${res.id}`)
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const handleGuidedEdit = () => {
    router.push(`/managed/agents/${agentId}/edit?guided=true`)
  }

  const handleArchive = () => {
    setConfirmDialog({
      open: true,
      title: t('managed.agents.archiveTitle'),
      description: t('managed.agents.archiveDescription', { name: agent?.name }),
      confirmLabel: t('common.archive'),
      destructive: false,
      onConfirm: async () => {
        try {
          await managedPost(`/agents/${stripIdPrefix(agentId)}/archive`, {})
          queryClient.invalidateQueries({ queryKey: ['agent', agentId] })
          setConfirmDialog((prev) => ({ ...prev, open: false }))
        } catch (e) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          toastOperationError(t, e, 'common.operationFailed')
        }
      },
    })
  }

  const handleDelete = async () => {
    try {
      const preview = await managedGet<DeletePreview>(
        `/agents/${stripIdPrefix(agentId)}/delete_preview`,
      )
      const desc = t('managed.agents.deleteDescription', {
        name: agent?.name,
        sessions: preview.sessions,
        tasks: preview.tasks,
        versions: preview.versions,
      })
      setConfirmDialog({
        open: true,
        title: t('managed.agents.deleteTitle', { name: agent?.name }),
        description: desc,
        confirmLabel: t('managed.agents.permanentlyDelete'),
        destructive: true,
        onConfirm: async () => {
          try {
            await managedDelete(`/agents/${stripIdPrefix(agentId)}`)
            router.push('/managed/agents')
          } catch (e) {
            setConfirmDialog((prev) => ({ ...prev, open: false }))
            toastOperationError(t, e, 'common.operationFailed')
          }
        },
      })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
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
  const menuItems = isArchived
    ? []
    : [
        {
          label: t('managed.agents.startSession'),
          onClick: handleStartSession,
          icon: <Play className="h-3.5 w-3.5" />,
        },
        {
          label: t('managed.agents.guidedEdit'),
          onClick: handleGuidedEdit,
          icon: <Sparkles className="h-3.5 w-3.5" />,
        },
        {
          label: t('common.archive'),
          onClick: handleArchive,
          icon: <Archive className="h-3.5 w-3.5" />,
          separator: true,
        },
      ]

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
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push(`/managed/agents/${agentId}/edit`)}
            >
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              {t('common.edit')}
            </Button>
            <ActionMenu items={menuItems} />
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
            onArchive={async (s) => {
              try {
                await managedPost(`/sessions/${stripIdPrefix(s.id)}/archive`, {})
                queryClient.invalidateQueries({
                  queryKey: ['agent-sessions', agentId],
                  exact: false,
                })
              } catch (e) {
                toastOperationError(t, e, 'common.operationFailed')
              }
            }}
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
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, open: false }))}
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
              {t('managed.agents.model')}
            </h3>
            <p className="font-mono text-sm text-muted-foreground">
              {selectedAgent.model?.id || '-'}
            </p>
          </section>

          {/* System prompt */}
          {(selectedAgent.system || selectedAgent.system_prompt) && (
            <section>
              <h3 className="mb-2 text-sm font-medium text-foreground">
                {t('managed.agents.systemPrompt')}
              </h3>
              <div className="relative">
                <pre className="max-h-[300px] overflow-x-auto overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-4 font-mono text-xs">
                  {selectedAgent.system || selectedAgent.system_prompt}
                </pre>
                <Button
                  variant="outline"
                  size="icon"
                  className="absolute right-2 top-2 h-7 w-7"
                  onClick={() =>
                    navigator.clipboard.writeText(
                      selectedAgent.system || selectedAgent.system_prompt || '',
                    )
                  }
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
}: {
  sessions: Session[]
  showArchived: boolean
  onArchivedChange: (v: boolean) => void
  onSelect: (s: Session) => void
  onArchive: (s: Session) => void
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
    { key: 'name', header: t('managed.table.name'), render: (s) => <span>{s.title || '-'}</span> },
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
          ...(s.archived_at
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
