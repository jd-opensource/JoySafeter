'use client'

import React, { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import { validateUniqueMcpServerName } from '@/lib/utils/mcp-validation'
import type { Agent } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from '@/components/ui/select'
import {
  AdvancedSection,
  FieldHelp,
  FormActionBar,
  FormFieldLabel,
  FormSectionCard,
  PageHeader,
  SkillVersionSelect,
} from '@/components/managed/shared'
import { CircleHelp, Plus, Trash2 } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { ModelSecretSelect } from '../../components/model-secret-select'
import { SearchableAgentConfigSelect } from '../../components/searchable-agent-config-select'

const BUILTIN_TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch']

const PERMISSION_MODES = [
  { value: 'bypassPermissions', labelKey: 'agents.edit.permBypass' },
  { value: 'default', labelKey: 'agents.edit.permAsk' },
]

interface McpServerEntry {
  name: string
  url: string
  /** Permission policy for this server's tools. Defaults to always_ask. */
  policy?: 'always_allow' | 'always_ask'
}

interface ManagedListResponse<T> {
  data: T[]
}

interface SkillListItem {
  id: string
  name?: string
  display_title?: string
  // Latest published version string, or null/undefined if never published.
  latest_version?: string | null
}

interface EnvironmentListItem {
  id: string
  name: string
}

interface SaveAgentVariables {
  agentId: string
  body: Record<string, unknown>
  requestScope: ManagedRequestScope
  runId: number
  scope: string
}

export default function AgentEditPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { t } = useTranslation()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const operationScope = `${managedScope.key}:${agentId ?? ''}`
  const saveRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const hydratedAgentScopeRef = useRef<string | null>(null)

  // ── Fetch agent ──
  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', managedScope.key, agentId],
    queryFn: () =>
      managedGet<Agent>(apiResourcePath('agents', agentId), managedRequestOptions(managedScope)),
    enabled: !!agentId && hasManagedRequestScope(managedScope),
  })

  // ── Fetch secrets ──
  const { data: secretsRes } = useQuery({
    queryKey: ['secrets', managedScope.key],
    queryFn: () =>
      managedGet<{ data: { name: string }[] }>('/secrets', managedRequestOptions(managedScope)),
    enabled: hasManagedRequestScope(managedScope),
  })
  const secrets = secretsRes?.data

  // ── Fetch skills ──
  const { data: skills } = useQuery({
    queryKey: ['skills', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<SkillListItem>>(
        '/skills',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  // ── Fetch environments ──
  const { data: environments } = useQuery({
    queryKey: ['environments', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<EnvironmentListItem>>(
        '/environments',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  // ── Basic info state ──
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [engineKind, setEngineKind] = useState('claude')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [systemPromptMode, setSystemPromptMode] = useState<'append' | 'replace'>('append')
  const [dirty, setDirty] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const systemPromptRequired = systemPromptMode === 'replace'
  const systemPromptValid = !systemPromptRequired || systemPrompt.trim().length > 0

  // ── MCP servers state ──
  const [mcpServers, setMcpServers] = useState<McpServerEntry[]>([])
  const [showMcpForm, setShowMcpForm] = useState(false)
  const [mcpName, setMcpName] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')

  // ── Tools state ──
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set(BUILTIN_TOOLS))

  // ── Skills state ──
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set())
  /** skill_id → chosen version keyword ("latest", "draft") or semver string. */
  const [skillVersions, setSkillVersions] = useState<Record<string, string>>({})

  // Only *published* skills can be newly referenced. We still show any skill
  // this agent already references (even if it's since become draft-only), so
  // the user can see and, if desired, remove that stale reference.
  const visibleSkills = useMemo(
    () => (skills || []).filter((s) => !!s.latest_version || selectedSkillIds.has(s.id)),
    [skills, selectedSkillIds],
  )

  const effectiveSelectedSkillIds = useMemo(() => {
    if (!skills) return selectedSkillIds
    const skillIds = new Set(skills.map((skill) => skill.id))
    return new Set(Array.from(selectedSkillIds).filter((id) => skillIds.has(id)))
  }, [selectedSkillIds, skills])

  const effectiveSkillVersions = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(skillVersions).filter(([id]) => effectiveSelectedSkillIds.has(id)),
      ),
    [effectiveSelectedSkillIds, skillVersions],
  )

  // ── Secret ref ──
  const [secretRef, setSecretRef] = useState('')

  // ── Environment ref ──
  const [environmentRef, setEnvironmentRef] = useState('')

  const effectiveSecretRef = useMemo(() => {
    if (!secretRef) return ''
    if (!secrets) return secretRef
    return secrets.some((secret) => secret.name === secretRef) ? secretRef : ''
  }, [secretRef, secrets])

  const effectiveEnvironmentRef = useMemo(() => {
    if (!environmentRef) return ''
    if (!environments) return environmentRef
    return environments.some((environment) => environment.id === environmentRef)
      ? environmentRef
      : ''
  }, [environmentRef, environments])

  // ── Permission mode ──
  const [permissionMode, setPermissionMode] = useState('bypassPermissions')

  const markDirty = () => setDirty(true)

  useEffect(() => {
    if (operationScopeRef.current !== operationScope) {
      operationScopeRef.current = operationScope
      managedRequestScopeRef.current = managedScope
      saveRunRef.current += 1
    }
  }, [operationScope])

  useEffect(
    () => () => {
      saveRunRef.current += 1
    },
    [],
  )

  // ── Populate state from agent data ──
  useEffect(() => {
    if (!agent) return
    const shouldHydrate = !dirty || hydratedAgentScopeRef.current !== operationScope
    if (!shouldHydrate) return

    setName(agent.name)
    setDescription(agent.description || '')
    setEngineKind(agent.engine_kind || 'claude')
    setSystemPrompt(agent.system || agent.system_prompt || '')
    setSystemPromptMode((agent.metadata?.system_prompt_mode as 'append' | 'replace') || 'append')

    // MCP servers — merge url (from mcp_servers) with policy (from the
    // matching mcp_toolset tool's default_config, default always_ask).
    const policyByServer = new Map<string, 'always_allow' | 'always_ask'>()
    for (const tool of agent.tools || []) {
      if (tool.type === 'mcp_toolset' && tool.mcp_server_name) {
        const pol = tool.default_config?.permission_policy?.type
        policyByServer.set(
          tool.mcp_server_name,
          pol === 'always_allow' ? 'always_allow' : 'always_ask',
        )
      }
    }
    setMcpServers(
      (agent.mcp_servers || []).map((m) => ({
        name: m.name,
        url: m.url,
        policy: policyByServer.get(m.name) || 'always_ask',
      })),
    )

    // Tools
    const toolset = agent.tools?.find((tool) => tool.type === 'agent_toolset_20260401')
    if (toolset && toolset.type === 'agent_toolset_20260401') {
      const enabled = new Set<string>()
      const configs = toolset.configs || []
      for (const cfg of configs) {
        if (cfg.enabled !== false) {
          enabled.add(cfg.name)
        }
      }
      if (configs.length === 0) {
        BUILTIN_TOOLS.forEach((tool) => enabled.add(tool))
      }
      setEnabledTools(enabled)

      const dc = toolset.default_config
      setPermissionMode(
        dc?.permission_policy?.type === 'always_ask' ? 'default' : 'bypassPermissions',
      )
    } else {
      setEnabledTools(new Set(BUILTIN_TOOLS))
      setPermissionMode('bypassPermissions')
    }

    // Skills
    const agentSkills = agent.skills || []
    setSelectedSkillIds(new Set(agentSkills.map((s) => s.skill_id)))
    setSkillVersions(
      Object.fromEntries(agentSkills.map((s) => [s.skill_id, s.version || 'latest'])),
    )

    // Secret ref
    setSecretRef(agent.secret_ref || '')

    // Environment ref
    setEnvironmentRef(agent.environment_ref || '')

    // Env vars
    hydratedAgentScopeRef.current = operationScope
    setDirty(false)
  }, [agent, dirty, operationScope])

  // ── Toggle tool ──
  const toggleTool = (tool: string) => {
    markDirty()
    setEnabledTools((prev) => {
      const next = new Set(prev)
      if (next.has(tool)) next.delete(tool)
      else next.add(tool)
      return next
    })
  }

  // ── MCP server helpers ──
  const addMcpServer = () => {
    const trimmedName = mcpName.trim()
    const trimmedUrl = mcpUrl.trim()
    if (!trimmedName || !trimmedUrl) return
    const nameError = validateUniqueMcpServerName(trimmedName, mcpServers)
    if (nameError) {
      toastOperationError(t, new Error(nameError), 'common.error')
      return
    }
    // URL scheme validation
    const urlError = validateUrlScheme(trimmedUrl)
    if (urlError) {
      toastOperationError(t, new Error(urlError), 'common.error')
      return
    }
    setMcpServers((prev) => [
      ...prev,
      { name: trimmedName, url: trimmedUrl, policy: 'always_ask' },
    ])
    markDirty()
    setMcpName('')
    setMcpUrl('')
    setShowMcpForm(false)
  }

  const setMcpPolicy = (index: number, policy: 'always_allow' | 'always_ask') => {
    markDirty()
    setMcpServers((prev) => prev.map((m, i) => (i === index ? { ...m, policy } : m)))
  }

  const removeMcpServer = (idx: number) => {
    markDirty()
    setMcpServers((prev) => prev.filter((_, i) => i !== idx))
  }

  // ── Skill toggle ──
  const toggleSkill = (skillId: string) => {
    markDirty()
    setSelectedSkillIds((prev) => {
      const next = new Set(prev)
      if (next.has(skillId)) next.delete(skillId)
      else next.add(skillId)
      return next
    })
  }

  // ── Env var helpers ──
  // ── Build tools payload ──
  const buildToolsPayload = () => {
    const tools: Record<string, unknown>[] = []
    // Agent toolset
    tools.push({
      type: 'agent_toolset_20260401',
      default_config: {
        permission_policy: {
          type: permissionMode === 'default' ? 'always_ask' : 'always_allow',
        },
      },
      configs: BUILTIN_TOOLS.map((t) => ({
        name: t,
        enabled: enabledTools.has(t),
      })),
    })
    // MCP toolsets
    for (const mcp of mcpServers) {
      tools.push({
        type: 'mcp_toolset',
        mcp_server_name: mcp.name,
        default_config: {
          permission_policy: { type: mcp.policy || 'always_ask' },
        },
      })
    }
    return tools
  }

  const buildSavePayload = (
    currentAgent = agent,
    scopeKey = managedRequestScopeRef.current.key,
  ): Record<string, unknown> => {
    const currentSecrets =
      queryClient.getQueryData<{ data?: { name: string }[] }>(['secrets', scopeKey])?.data ??
      secrets
    const currentEnvironments =
      queryClient.getQueryData<ManagedListResponse<EnvironmentListItem>>(['environments', scopeKey])
        ?.data ?? environments
    const currentSkills =
      queryClient.getQueryData<ManagedListResponse<SkillListItem>>(['skills', scopeKey])?.data ??
      skills

    const currentSecretRef =
      secretRef && (!currentSecrets || currentSecrets.some((secret) => secret.name === secretRef))
        ? secretRef
        : ''
    const currentEnvironmentRef =
      environmentRef &&
      (!currentEnvironments ||
        currentEnvironments.some((environment) => environment.id === environmentRef))
        ? environmentRef
        : ''
    const currentSkillIds = currentSkills ? new Set(currentSkills.map((skill) => skill.id)) : null
    const currentSelectedSkillIds = currentSkillIds
      ? Array.from(selectedSkillIds).filter((id) => currentSkillIds.has(id))
      : Array.from(selectedSkillIds)

    return {
      version: currentAgent!.version || 1,
      name,
      description: description || null,
      engine_kind: engineKind,
      system: systemPrompt || null,
      mcp_servers: mcpServers
        .filter((s) => s.name && s.url)
        .map((m) => ({ type: 'url', name: m.name, url: m.url })),
      env: currentAgent?.env || {},
      tools: buildToolsPayload(),
      skills: currentSelectedSkillIds.map((id) => ({
        type: 'custom' as const,
        skill_id: id,
        version: effectiveSkillVersions[id] || 'latest',
      })),
      ...(currentSecretRef ? { secret_ref: currentSecretRef } : {}),
      ...(currentEnvironmentRef ? { environment_ref: currentEnvironmentRef } : {}),
      metadata: { system_prompt_mode: systemPromptMode },
    }
  }

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${agentId ?? ''}`
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const currentEditableAgent = () => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const current = queryClient.getQueryData<Agent>(['agent', getCurrentManagedScope(), agentId])
    return current?.id === agentId && !current.archived_at ? current : null
  }

  const isCurrentSaveRun = (runId: number, scope: string) =>
    saveRunRef.current === runId &&
    operationScopeRef.current === scope &&
    getCurrentOperationScope() === scope

  // ── Save mutation ──
  const mutation = useMutation({
    mutationFn: async ({ agentId, body, requestScope, runId, scope }: SaveAgentVariables) => {
      if (!isCurrentSaveRun(runId, scope)) return undefined
      if (!currentProjectAllowsWrite()) return undefined
      return managedPost(
        apiResourcePath('agents', agentId),
        body,
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { agentId, requestScope, runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['agent', requestScope.key, agentId] })
      router.push(`/managed/agents/${agentId}`)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  if (isLoading || !agent) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!agent.archived_at
  const formReadOnly = isArchived || projectReadOnly

  return (
    <div>
      <PageHeader
        title={t('agents.editTitle', { name: agent.name })}
        breadcrumb={[
          { label: t('managed.agents.title'), to: '/managed/agents' },
          { label: agent.name, to: `/managed/agents/${agentId}` },
          { label: t('common.edit') },
        ]}
      />

      <div className="max-w-2xl space-y-8">
        {isArchived && (
          <Alert>
            <AlertDescription>{t('managed.errors.resourceArchived')}</AlertDescription>
          </Alert>
        )}
        {projectReadOnly && !isArchived && (
          <Alert>
            <AlertDescription>{t('managed.errors.projectArchived')}</AlertDescription>
          </Alert>
        )}

        <fieldset disabled={formReadOnly} className="space-y-6">
          {/* ───────── Basic Info ───────── */}
          <FormSectionCard
            title={t('agents.edit.basicInfo')}
            description={t(
              'managed.agents.basicSettingsDesc',
              '设置智能体名称、模型密钥、引擎和系统提示词。',
            )}
          >
            <div>
              <FormFieldLabel required className="mb-1.5">
                {t('managed.agents.name')}
              </FormFieldLabel>
              <Input
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  markDirty()
                }}
              />
            </div>

            <div>
              <FormFieldLabel optional={t('managed.agents.formOptional')} className="mb-1.5">
                {t('managed.agents.description')}
              </FormFieldLabel>
              <Input
                value={description}
                onChange={(e) => {
                  setDescription(e.target.value)
                  markDirty()
                }}
                placeholder={t('managed.agents.descriptionPlaceholder')}
              />
            </div>

            <div>
              <FormFieldLabel
                required
                tooltip={t('managed.agents.engineKindDesc')}
                className="mb-1.5"
              >
                {t('managed.agents.engineKind')}
              </FormFieldLabel>
              <Select
                value={engineKind}
                onValueChange={(value) => {
                  setEngineKind(value)
                  markDirty()
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="claude">{t('managed.agents.engineClaude')}</SelectItem>
                  <SelectItem value="codex">{t('managed.agents.engineCodex')}</SelectItem>
                  <SelectItem value="native">{t('managed.agents.engineNative')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* ───────── Secret Reference ───────── */}
            <section className="space-y-3">
              <h3 className="border-b border-border pb-2 text-sm font-semibold text-foreground">
                {t('agents.edit.secretRef')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.agents.formOptional')}
                </span>
              </h3>
              {secrets && secrets.length > 0 ? (
                <ModelSecretSelect
                  value={secretRef}
                  secrets={secrets}
                  placeholder={t('agents.edit.selectSecret')}
                  noneLabel={t('agents.edit.noSelection')}
                  searchPlaceholder={t('agents.edit.searchSecret')}
                  emptyText={t('agents.edit.noSecretMatch')}
                  createLabel={t('agents.edit.createSecret')}
                  clearSearchLabel={t('agents.edit.clearSearch')}
                  onChange={(value) => {
                    setSecretRef(value)
                    markDirty()
                  }}
                  onCreate={() => window.open('/managed/secrets?create=llm', '_blank')}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t('managed.agents.create.noSecrets')}
                </p>
              )}
            </section>

            {/* ───────── Environment Reference ───────── */}
            <section className="space-y-3">
              <div className="flex items-center gap-1.5 border-b border-border pb-2">
                <h3 className="text-sm font-semibold text-foreground">
                  {t('agents.edit.environmentRef')}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t('managed.agents.formOptional')}
                  </span>
                </h3>
                <FieldHelp text={t('agents.edit.environmentRefHint')} />
              </div>
              {environments && environments.length > 0 ? (
                <SearchableAgentConfigSelect
                  value={environmentRef || '__none__'}
                  options={environments.map((env) => ({
                    value: env.id,
                    label: env.name,
                    searchText: env.id,
                  }))}
                  placeholder={t('agents.edit.selectEnvironment')}
                  noneLabel={t('agents.edit.noSelection')}
                  searchPlaceholder={t('agents.edit.searchEnvironment')}
                  emptyText={t('agents.edit.noEnvironmentMatch')}
                  createLabel={t('agents.edit.createEnvironment')}
                  clearSearchLabel={t('agents.edit.clearSearch')}
                  onChange={(value) => {
                    setEnvironmentRef(value)
                    markDirty()
                  }}
                  onCreate={() => window.open('/managed/environments?create=1', '_blank')}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t('agents.edit.noEnvironments')}
                  <button
                    type="button"
                    onClick={() => window.open('/managed/environments?create=1', '_blank')}
                    className="ml-2 text-primary hover:underline"
                  >
                    {t('agents.edit.createEnvironment')}
                  </button>
                </p>
              )}
            </section>

            <div>
              <FormFieldLabel
                required={systemPromptRequired}
                optional={!systemPromptRequired ? t('managed.agents.formOptional') : undefined}
                className="mb-1.5"
              >
                {t('managed.agents.systemPrompt')}
              </FormFieldLabel>
              <textarea
                className="flex min-h-[200px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                value={systemPrompt}
                onChange={(e) => {
                  setSystemPrompt(e.target.value)
                  markDirty()
                }}
                placeholder={t('managed.agents.systemPromptPlaceholder')}
              />
              <div className="mt-2 flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="radio"
                    name="system_prompt_mode"
                    value="append"
                    checked={systemPromptMode === 'append'}
                    onChange={() => {
                      setSystemPromptMode('append')
                      markDirty()
                    }}
                    className="accent-primary"
                  />
                  {t('managed.agents.promptModeAppend', '追加模式')}
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <CircleHelp className="h-3.5 w-3.5 cursor-help text-muted-foreground/60" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-[240px] text-xs">
                        {t(
                          'managed.agents.promptModeAppendTooltip',
                          '系统提示追加到引擎（Claude Code）内置提示后面，保留引擎的行为规范和最佳实践指引',
                        )}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </label>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="radio"
                    name="system_prompt_mode"
                    value="replace"
                    checked={systemPromptMode === 'replace'}
                    onChange={() => {
                      setSystemPromptMode('replace')
                      markDirty()
                    }}
                    className="accent-primary"
                  />
                  {t('managed.agents.promptModeReplace', '替换模式')}
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <CircleHelp className="h-3.5 w-3.5 cursor-help text-muted-foreground/60" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-[240px] text-xs">
                        {t(
                          'managed.agents.promptModeReplaceTooltip',
                          '完全替换引擎内置提示，由你的系统提示全权控制 Agent 行为。工具（Bash/文件读写等）仍可正常使用',
                        )}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </label>
              </div>
            </div>
          </FormSectionCard>

          <AdvancedSection
            open={showAdvanced}
            onOpenChange={setShowAdvanced}
            title={t('managed.agents.create.advancedOptions', '高级选项')}
            summary={t('managed.agents.edit.advancedSummary', 'MCP、工具、Skills')}
          >
            {/* ───────── MCP Servers ───────── */}
            <section className="space-y-3">
              <div className="flex items-center justify-between border-b border-border pb-2">
                <h3 className="text-sm font-semibold text-foreground">
                  {t('agents.edit.mcpServers')}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t('managed.agents.formOptional')}
                  </span>
                </h3>
                <button
                  type="button"
                  onClick={() => setShowMcpForm(true)}
                  className="flex h-6 w-6 items-center justify-center rounded border border-border transition-colors hover:bg-accent"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>

              {mcpServers.length === 0 && !showMcpForm && (
                <p className="py-2 text-center text-sm text-muted-foreground">
                  {t('managed.agents.create.noMcpServers')}
                </p>
              )}

              {mcpServers.map((m, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{m.name}</span>
                  <span className="flex-1 truncate text-muted-foreground">{m.url}</span>
                  <select
                    value={m.policy || 'always_ask'}
                    onChange={(e) =>
                      setMcpPolicy(i, e.target.value as 'always_allow' | 'always_ask')
                    }
                    className="h-7 rounded border border-border bg-background px-1.5 text-xs"
                    title={t('managed.agents.create.mcpPolicyHint')}
                  >
                    <option value="always_ask">{t('managed.policy.alwaysAsk')}</option>
                    <option value="always_allow">{t('managed.policy.alwaysAllow')}</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => removeMcpServer(i)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}

              {showMcpForm && (
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <Input
                      placeholder={t('managed.agents.create.mcpNamePlaceholder')}
                      value={mcpName}
                      onChange={(e) => setMcpName(e.target.value)}
                      className="text-sm"
                    />
                  </div>
                  <div className="flex-[2]">
                    <Input
                      placeholder={t('managed.agents.create.mcpUrlPlaceholder')}
                      value={mcpUrl}
                      onChange={(e) => setMcpUrl(e.target.value)}
                      className="text-sm"
                    />
                  </div>
                  <Button size="sm" variant="outline" onClick={addMcpServer}>
                    {t('managed.agents.create.add')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setShowMcpForm(false)
                      setMcpName('')
                      setMcpUrl('')
                    }}
                  >
                    {t('common.cancel')}
                  </Button>
                </div>
              )}
            </section>

            {/* ───────── Tools ───────── */}
            <section className="space-y-3">
              <h3 className="border-b border-border pb-2 text-sm font-semibold text-foreground">
                {t('agents.edit.tools')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.agents.formOptionalDefaultEnabled')}
                </span>
              </h3>
              <div className="grid grid-cols-4 gap-3">
                {BUILTIN_TOOLS.map((tool) => (
                  <label key={tool} className="flex cursor-pointer select-none items-center gap-2">
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded border transition-colors ${
                        enabledTools.has(tool)
                          ? 'border-emerald-400 bg-emerald-400 text-white'
                          : 'border-border bg-background'
                      }`}
                      onClick={() => toggleTool(tool)}
                    >
                      {enabledTools.has(tool) && (
                        <svg
                          className="h-3 w-3"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={3}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </span>
                    <span className="text-sm text-foreground" onClick={() => toggleTool(tool)}>
                      {tool}
                    </span>
                  </label>
                ))}
              </div>

              {/* Permission mode — applies to the whole toolset */}
              <div>
                <FormFieldLabel
                  optional={t('managed.agents.formOptionalDefaultEnabled')}
                  tooltip={t(
                    'managed.agents.edit.permissionModeHint',
                    '控制 Agent 使用工具（如执行命令、写文件）时是否需要人工确认。「跳过确认」允许 Agent 自主执行所有操作。',
                  )}
                  className="mb-1.5"
                >
                  {t('agents.edit.permissionMode')}
                </FormFieldLabel>
                <select
                  className="flex w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  value={permissionMode}
                  onChange={(e) => {
                    setPermissionMode(e.target.value)
                    markDirty()
                  }}
                >
                  {PERMISSION_MODES.map((m) => (
                    <option key={m.value} value={m.value}>
                      {t(m.labelKey)}
                    </option>
                  ))}
                </select>
              </div>
            </section>

            <section className="space-y-3">
              <h3 className="border-b border-border pb-2 text-sm font-semibold text-foreground">
                {t('agents.edit.skills')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.agents.formOptional')}
                </span>
              </h3>
              {!visibleSkills || visibleSkills.length === 0 ? (
                <p className="py-2 text-center text-sm text-muted-foreground">
                  {t('managed.agents.create.noSkills')}{' '}
                  <Link href="/managed/skills" className="text-emerald-500 hover:underline">
                    {t('managed.agents.create.goCreateSkill')} &rarr;
                  </Link>
                </p>
              ) : (
                <div className="space-y-2">
                  {visibleSkills.map((skill) => {
                    const isSelected = selectedSkillIds.has(skill.id)
                    return (
                      <div key={skill.id} className="flex items-center gap-2">
                        <label className="flex min-w-0 flex-1 cursor-pointer select-none items-center gap-2">
                          <span
                            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                              isSelected
                                ? 'border-emerald-400 bg-emerald-400 text-white'
                                : 'border-border bg-background'
                            }`}
                            onClick={() => toggleSkill(skill.id)}
                          >
                            {isSelected && (
                              <svg
                                className="h-3 w-3"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                strokeWidth={3}
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  d="M5 13l4 4L19 7"
                                />
                              </svg>
                            )}
                          </span>
                          <span
                            className="truncate text-sm text-foreground"
                            onClick={() => toggleSkill(skill.id)}
                          >
                            {skill.display_title || skill.name || skill.id}
                          </span>
                        </label>
                        {isSelected && (
                          <SkillVersionSelect
                            skillId={skill.id}
                            value={skillVersions[skill.id] || 'latest'}
                            onChange={(v) => {
                              setSkillVersions((prev) => ({ ...prev, [skill.id]: v }))
                              markDirty()
                            }}
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          </AdvancedSection>
        </fieldset>

        {/* ───────── Action buttons ───────── */}
        <FormActionBar className="mx-0">
          <Button
            onClick={() => {
              const current = currentEditableAgent()
              if (!current) return
              const requestScope = managedRequestScopeRef.current
              const scope = operationScopeRef.current
              if (!currentOperationScopeIsActive(scope)) return
              const runId = saveRunRef.current + 1
              saveRunRef.current = runId
              mutation.mutate({
                agentId,
                body: buildSavePayload(current, requestScope.key),
                requestScope,
                runId,
                scope,
              })
            }}
            disabled={formReadOnly || mutation.isPending || !name.trim() || !systemPromptValid}
          >
            {mutation.isPending ? t('managed.agents.saving') : t('managed.agents.saveChanges')}
          </Button>
          <Button variant="outline" onClick={() => router.push(`/managed/agents/${agentId}`)}>
            {t('common.cancel')}
          </Button>
        </FormActionBar>
      </div>
    </div>
  )
}
