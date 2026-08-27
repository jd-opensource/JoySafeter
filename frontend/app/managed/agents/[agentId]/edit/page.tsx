'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleHelp } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import React, { useEffect, useMemo, useRef, useState } from 'react'

import { McpServerEditor } from '@/components/managed/agent/mcp-server-editor'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { getEnabledEngines } from '@/lib/managed/llm-catalog'
import { serializeMcpServerEntries, type McpServerEntry } from '@/lib/managed/mcp-config'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import type { Agent, Credential, Environment } from '@/types/managed'
import {
  parseAgentId,
  parseCredentialId,
  parseEnvironmentId,
  type AgentId,
  type CredentialId,
  type EnvironmentId,
  type SkillId,
} from '@/types/entity-id'
import { parseSkillResponse } from '@/lib/managed/skill-response-parsers'
import { parseAgentResponse } from '@/lib/managed/agent-response-parsers'
import { parseEnvironmentListResponse } from '@/lib/managed/environment-response-parsers'
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
  withEntityRouteGuard,
} from '@/components/managed/shared'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import {
  compatibleCredentialsQueryPrefix,
  useCompatibleCredentials,
  useModelConnectionByName,
} from '@/hooks/managed/use-compatible-credentials'
import { CompatibleCredentialPicker } from '@/components/managed/llm/compatible-credential-picker'
import { SearchableAgentConfigSelect } from '../../components/searchable-agent-config-select'

const BUILTIN_TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch']

const PERMISSION_MODES = [
  { value: 'bypassPermissions', labelKey: 'agents.edit.permBypass' },
  { value: 'default', labelKey: 'agents.edit.permAsk' },
]

interface ManagedListResponse<T> {
  data: T[]
}

interface SkillListItem {
  id: SkillId
  name?: string
  display_title?: string
  // Latest published version string, or null/undefined if never published.
  latest_version?: string | null
}

interface SaveAgentVariables {
  agentId: AgentId
  body: Record<string, unknown>
  requestScope: ManagedRequestScope
  runId: number
  scope: string
}

export default withEntityRouteGuard(AgentEditPageInner, {
  kind: 'agent',
  paramKey: 'agentId',
  backTo: '/managed/agents',
})

function AgentEditPageInner({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId: rawAgentId } = React.use(params)
  const agentId = parseAgentId(rawAgentId)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { t } = useTranslation()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const operationScope = `${managedScope.key}:${agentId ?? ''}`
  const saveRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const hydratedAgentScopeRef = useRef<string | null>(null)

  // ── Fetch agent ──
  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', managedScope.key, agentId],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('agents', agentId),
        managedRequestOptions(managedScope),
      ).then(parseAgentResponse),
    enabled: !!agentId && hasManagedRequestScope(managedScope),
  })

  // ── Fetch skills ──
  const { data: skills } = useQuery({
    queryKey: ['skills', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<unknown>>(
        '/skills',
        managedRequestOptions(managedScope),
      )
      return (res.data || []).map(parseSkillResponse)
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  // ── Fetch environments ──
  const { data: environments } = useQuery({
    queryKey: ['environments', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<unknown>>(
        '/environments',
        managedRequestOptions(managedScope),
      )
      return parseEnvironmentListResponse(res.data || [])
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  // ── Basic info state ──
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [engineKind, setEngineKind] = useState('')
  const [originalEngineKind, setOriginalEngineKind] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [systemPromptMode, setSystemPromptMode] = useState<'append' | 'replace'>('append')
  const [dirty, setDirty] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const systemPromptRequired = systemPromptMode === 'replace'
  const systemPromptValid = !systemPromptRequired || systemPrompt.trim().length > 0

  // ── MCP servers state ──
  const [mcpServers, setMcpServers] = useState<McpServerEntry[]>([])

  // ── Tools state ──
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set(BUILTIN_TOOLS))

  // ── Skills state ──
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<SkillId>>(new Set())
  /** skill_id → chosen published version keyword or semver string. */
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
        Object.entries(skillVersions).filter(([id]) =>
          Array.from(effectiveSelectedSkillIds).some((skillId) => skillId === id),
        ),
      ),
    [effectiveSelectedSkillIds, skillVersions],
  )

  // ── Model Connection reference ──
  const [modelCredentialId, setModelCredentialId] = useState<CredentialId | ''>('')
  const enabledEngines = useMemo(
    () => (catalogQuery.data ? getEnabledEngines(catalogQuery.data) : []),
    [catalogQuery.data],
  )
  const engineUnavailable =
    catalogQuery.isSuccess && !enabledEngines.some((engine) => engine.id === engineKind)
  const compatibleCredentialsQuery = useCompatibleCredentials({ engineId: engineKind })
  const secrets = compatibleCredentialsQuery.data
  const selectedCredentialIsCompatible =
    !modelCredentialId || Boolean(secrets?.some((secret) => secret.id === modelCredentialId))
  const credentialConflict =
    Boolean(modelCredentialId) &&
    compatibleCredentialsQuery.isSuccess &&
    !selectedCredentialIsCompatible
  const conflictCredentialQuery = useModelConnectionByName({
    name: modelCredentialId,
    enabled: credentialConflict,
  })
  const modelCredentialCompatibilityBlocked =
    Boolean(modelCredentialId) && (!compatibleCredentialsQuery.isSuccess || credentialConflict)

  // ── Environment ID ──
  const [environmentId, setEnvironmentId] = useState<EnvironmentId | ''>('')

  const effectiveEnvironmentId = useMemo(() => {
    if (!environmentId) return ''
    if (!environments) return environmentId
    return environments.some((environment) => environment.id === environmentId) ? environmentId : ''
  }, [environmentId, environments])

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
    const hydratedEngineKind = agent.engine_kind
    setEngineKind(hydratedEngineKind)
    setOriginalEngineKind(hydratedEngineKind)
    setSystemPrompt(agent.system || '')
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
        ...m,
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

    // Model Connection reference
    setModelCredentialId(agent.model_credential_id || '')

    // Environment ID
    setEnvironmentId(agent.environment_id || '')

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

  const updateMcpServers = (next: McpServerEntry[]) => {
    markDirty()
    setMcpServers(next)
  }

  // ── Skill toggle ──
  const toggleSkill = (skillId: SkillId) => {
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
    const currentCredentials =
      queryClient
        .getQueriesData<Credential[]>({
          queryKey: compatibleCredentialsQueryPrefix(scopeKey, engineKind),
        })
        .at(-1)?.[1] ?? secrets
    const currentEnvironments =
      queryClient.getQueryData<Environment[]>(['environments', scopeKey]) ?? environments
    const currentSkills = queryClient.getQueryData<SkillListItem[]>(['skills', scopeKey]) ?? skills

    const currentModelCredentialId =
      modelCredentialId &&
      (!currentCredentials || currentCredentials.some((secret) => secret.id === modelCredentialId))
        ? modelCredentialId
        : ''
    const currentEnvironmentId =
      environmentId &&
      (!currentEnvironments ||
        currentEnvironments.some((environment) => environment.id === environmentId))
        ? environmentId
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
      mcp_servers: serializeMcpServerEntries(mcpServers),
      env: currentAgent?.env || {},
      tools: buildToolsPayload(),
      skills: currentSelectedSkillIds.map((id) => ({
        type: 'custom' as const,
        skill_id: id,
        version: effectiveSkillVersions[id] || 'latest',
      })),
      model_credential_id: currentModelCredentialId
        ? parseCredentialId(currentModelCredentialId)
        : null,
      ...(currentEnvironmentId ? { environment_id: currentEnvironmentId } : {}),
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
    getCurrentOperationScope() === scope &&
    currentProjectAllowsWrite()

  // ── Save mutation ──
  const mutation = useMutation({
    mutationFn: async ({ agentId, body, requestScope, runId, scope }: SaveAgentVariables) => {
      if (!isCurrentSaveRun(runId, scope)) return undefined
      if (!currentProjectAllowsWrite()) return undefined
      return managedPost<unknown>(
        apiResourcePath('agents', agentId),
        body,
        managedRequestOptions(requestScope),
      ).then(parseAgentResponse)
    },
    onSuccess: (updatedAgent, { agentId, requestScope, runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope) || !updatedAgent) return
      queryClient.setQueryData(['agent', requestScope.key, agentId], updatedAgent)
      queryClient.invalidateQueries({ queryKey: ['agents', requestScope.key] })
      queryClient.invalidateQueries({ queryKey: ['agent-versions', requestScope.key, agentId] })
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
              '设置智能体名称、模型接入、引擎和系统提示词。',
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
                  {engineUnavailable ? (
                    <SelectItem value={engineKind} disabled>
                      {engineKind} · {t('managed.llm.engineUnavailable')}
                    </SelectItem>
                  ) : null}
                  {enabledEngines.map((engine) => (
                    <SelectItem key={engine.id} value={engine.id}>
                      {engine.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* ───────── Model Connection Reference ───────── */}
            <section className="space-y-3">
              <h3 className="border-b border-border pb-2 text-sm font-semibold text-foreground">
                {t('agents.edit.modelCredentialId')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.agents.formOptional')}
                </span>
              </h3>
              <CompatibleCredentialPicker
                engineId={engineKind}
                value={modelCredentialId}
                allowNone
                disabled={formReadOnly}
                conflictCredential={conflictCredentialQuery.data ?? null}
                conflictValue={credentialConflict ? modelCredentialId : undefined}
                conflictMessage={
                  credentialConflict ? t('managed.llm.incompatibleWithSelectedEngine') : undefined
                }
                onChange={(value) => {
                  setModelCredentialId(value)
                  markDirty()
                }}
                onCreateRequested={() =>
                  window.open('/managed/credentials?tab=models&create=model', '_blank')
                }
              />
              {credentialConflict ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={formReadOnly}
                    onClick={() => {
                      setModelCredentialId('')
                      markDirty()
                    }}
                  >
                    {t('managed.llm.reselectConfiguration')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={formReadOnly}
                    onClick={() => {
                      setEngineKind(originalEngineKind)
                      markDirty()
                    }}
                  >
                    {t('managed.llm.restoreOriginalEngine')}
                  </Button>
                </div>
              ) : null}
            </section>

            {/* ───────── Environment ID ───────── */}
            <section className="space-y-3">
              <div className="flex items-center gap-1.5 border-b border-border pb-2">
                <h3 className="text-sm font-semibold text-foreground">
                  {t('agents.edit.environmentId')}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t('managed.agents.formOptional')}
                  </span>
                </h3>
                <FieldHelp text={t('agents.edit.environmentIdHint')} />
              </div>
              {environments && environments.length > 0 ? (
                <SearchableAgentConfigSelect
                  value={effectiveEnvironmentId}
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
                    setEnvironmentId(value ? parseEnvironmentId(value) : '')
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
            <McpServerEditor
              value={mcpServers}
              onChange={updateMcpServers}
              disabled={projectReadOnly}
            />

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
            disabled={
              formReadOnly ||
              mutation.isPending ||
              !name.trim() ||
              !systemPromptValid ||
              modelCredentialCompatibilityBlocked ||
              engineUnavailable ||
              !catalogQuery.isSuccess
            }
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
