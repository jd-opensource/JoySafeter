'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleHelp, Plus, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  AdvancedSection,
  FormActionBar,
  FormFieldLabel,
  FormSectionCard,
  FieldHelp,
  SkillVersionSelect,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from '@/components/ui/select'
import { managedGet, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import type { SkillRuntimeEligibility } from '@/types/managed'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useProjectStore } from '@/stores/managed/project-store'
import { ModelSecretSelect } from './model-secret-select'
import { SearchableAgentConfigSelect } from './searchable-agent-config-select'

const BUILTIN_TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch']

const PERMISSION_MODES = [
  { value: 'bypassPermissions', labelKey: 'managed.agents.edit.permBypass' },
  { value: 'default', labelKey: 'managed.agents.edit.permAsk' },
]

interface McpServerEntry {
  name: string
  url: string
  /** Permission policy for this server's tools. Defaults to always_ask
   * (matches the Managed Agents default for mcp_toolset). */
  policy?: 'always_allow' | 'always_ask'
}

interface ManagedListResponse<T> {
  data: T[]
}

interface SkillListItem {
  id: string
  name: string
  // Latest published version string, or null/undefined if never published.
  // Agents can only reference published skills, so the picker hides rows
  // without a published version.
  latest_version?: string | null
  runtime_eligibility?: SkillRuntimeEligibility | null
}

function skillUnavailableReason(skill: SkillListItem): string | null {
  if (!skill.latest_version) return 'no_published_version'
  if (skill.runtime_eligibility && !skill.runtime_eligibility.usable) {
    return skill.runtime_eligibility.reason || 'runtime_not_ready'
  }
  return null
}

interface EnvironmentListItem {
  id: string
  name: string
}

interface CreateAgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (agentId: string) => void
}

export function CreateAgentDialog({ open, onOpenChange, onCreated }: CreateAgentDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const createRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [engineKind, setEngineKind] = useState('claude')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [systemPromptMode, setSystemPromptMode] = useState<'append' | 'replace'>('append')
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set(BUILTIN_TOOLS))
  const [mcpServers, setMcpServers] = useState<McpServerEntry[]>([])
  const [showMcpForm, setShowMcpForm] = useState(false)
  const [mcpName, setMcpName] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')
  const [secretRef, setSecretRef] = useState('')
  const [secretSelectionCleared, setSecretSelectionCleared] = useState(false)
  const [environmentRef, setEnvironmentRef] = useState('')
  const [permissionMode, setPermissionMode] = useState('bypassPermissions')
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set())
  /** skill_id → chosen version keyword ("latest", "draft") or semver string. */
  const [skillVersions, setSkillVersions] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const systemPromptRequired = systemPromptMode === 'replace'
  const systemPromptValid = !systemPromptRequired || systemPrompt.trim().length > 0

  const { data: secretsRes } = useQuery({
    queryKey: ['secrets', managedScope.key],
    queryFn: () =>
      managedGet<{ data: { name: string }[] }>('/secrets', managedRequestOptions(managedScope)),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const secrets = secretsRes?.data

  const { data: skills } = useQuery({
    queryKey: ['skills', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<SkillListItem>>(
        '/skills',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: open && hasManagedRequestScope(managedScope),
  })

  const { data: environments } = useQuery({
    queryKey: ['environments', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<EnvironmentListItem>>(
        '/environments',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: open && hasManagedRequestScope(managedScope),
  })

  const effectiveSecretRef = useMemo(() => {
    if (!secrets || secrets.length === 0) return ''
    const secretNames = new Set(secrets.map((secret) => secret.name))
    if (secretRef && secretNames.has(secretRef)) return secretRef
    return secretSelectionCleared ? '' : secrets[0].name
  }, [secrets, secretRef, secretSelectionCleared])

  const effectiveEnvironmentRef = useMemo(() => {
    if (!environmentRef || !environments) return ''
    return environments.some((environment) => environment.id === environmentRef)
      ? environmentRef
      : ''
  }, [environments, environmentRef])

  const effectiveSelectedSkillIds = useMemo(() => {
    if (!skills) return new Set<string>()
    const skillIds = new Set(skills.map((skill) => skill.id))
    return new Set(Array.from(selectedSkillIds).filter((id) => skillIds.has(id)))
  }, [skills, selectedSkillIds])

  const effectiveSkillVersions = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(skillVersions).filter(([id]) => effectiveSelectedSkillIds.has(id)),
      ),
    [effectiveSelectedSkillIds, skillVersions],
  )

  const reset = () => {
    setName('')
    setDescription('')
    setEngineKind('claude')
    setSystemPrompt('')
    setEnabledTools(new Set(BUILTIN_TOOLS))
    setMcpServers([])
    setShowMcpForm(false)
    setMcpName('')
    setMcpUrl('')
    setSecretRef('')
    setSecretSelectionCleared(false)
    setEnvironmentRef('')
    setPermissionMode('bypassPermissions')
    setSelectedSkillIds(new Set())
    setSkillVersions({})
    setSubmitting(false)
    setShowAdvanced(false)
  }

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    reset()
    onOpenChange(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [managedScope.key])

  useEffect(
    () => () => {
      createRunRef.current += 1
    },
    [],
  )

  const toggleTool = (tool: string) => {
    setEnabledTools((prev) => {
      const next = new Set(prev)
      if (next.has(tool)) next.delete(tool)
      else next.add(tool)
      return next
    })
  }

  const addMcpServer = () => {
    if (!mcpName.trim() || !mcpUrl.trim()) return
    const urlError = validateUrlScheme(mcpUrl.trim())
    if (urlError) {
      toastOperationError(t, new Error(urlError), 'common.error')
      return
    }
    setMcpServers((prev) => [
      ...prev,
      { name: mcpName.trim(), url: mcpUrl.trim(), policy: 'always_ask' },
    ])
    setMcpName('')
    setMcpUrl('')
    setShowMcpForm(false)
  }

  const setMcpPolicy = (index: number, policy: 'always_allow' | 'always_ask') => {
    setMcpServers((prev) => prev.map((m, i) => (i === index ? { ...m, policy } : m)))
  }

  const removeMcpServer = (idx: number) => {
    setMcpServers((prev) => prev.filter((_, i) => i !== idx))
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const isCurrentCreateRun = (runId: number, scope: string) =>
    runId === createRunRef.current &&
    scope === managedScopeRef.current &&
    scope === getCurrentManagedScope() &&
    currentProjectAllowsWrite()

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    scope === getCurrentManagedScope()

  const handleSubmit = async () => {
    if (!name.trim()) return
    if (!currentProjectAllowsWrite()) {
      reset()
      onOpenChange(false)
      return
    }
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    if (!currentManagedScopeIsActive(scopeAtStart)) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    setSubmitting(true)
    try {
      const tools: Record<string, unknown>[] = []
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
      for (const mcp of mcpServers) {
        tools.push({
          type: 'mcp_toolset',
          mcp_server_name: mcp.name,
          default_config: {
            permission_policy: { type: mcp.policy || 'always_ask' },
          },
        })
      }

      const currentSecrets =
        queryClient.getQueryData<{ data?: { name: string }[] }>(['secrets', scopeAtStart])?.data ??
        secrets
      const currentEnvironments =
        queryClient.getQueryData<ManagedListResponse<EnvironmentListItem>>([
          'environments',
          scopeAtStart,
        ])?.data ?? environments
      const currentSkills =
        queryClient.getQueryData<SkillListItem[]>(['skills', scopeAtStart]) ?? skills

      const currentSecretRef = (() => {
        if (!currentSecrets) return effectiveSecretRef
        if (currentSecrets.length === 0) return ''
        const secretNames = new Set(currentSecrets.map((secret) => secret.name))
        if (secretRef && secretNames.has(secretRef)) return secretRef
        return secretSelectionCleared ? '' : currentSecrets[0].name
      })()
      const currentEnvironmentRef =
        environmentRef &&
        (!currentEnvironments ||
          currentEnvironments.some((environment) => environment.id === environmentRef))
          ? environmentRef
          : ''
      const currentSkillIds = currentSkills ? new Set(currentSkills.map((skill) => skill.id)) : null
      const currentSelectedSkillIds = currentSkillIds
        ? Array.from(selectedSkillIds).filter((id) => currentSkillIds.has(id))
        : Array.from(effectiveSelectedSkillIds)
      const currentSkillVersions = Object.fromEntries(
        Object.entries(skillVersions).filter(([id]) => currentSelectedSkillIds.includes(id)),
      )

      const res = await managedPost<{ id: string }>(
        '/agents',
        {
          name: name.trim(),
          description: description.trim() || null,
          engine_kind: engineKind,
          system_prompt: systemPrompt || null,
          metadata: { system_prompt_mode: systemPromptMode },
          ...(currentSecretRef ? { secret_ref: currentSecretRef } : {}),
          ...(currentEnvironmentRef ? { environment_ref: currentEnvironmentRef } : {}),
          tools,
          mcp_servers: mcpServers.map((m) => ({ type: 'url', name: m.name, url: m.url })),
          skill_ids: currentSelectedSkillIds,
          skills: currentSelectedSkillIds.map((id) => ({
            type: 'custom' as const,
            skill_id: id,
            version: currentSkillVersions[id] || 'latest',
          })),
        },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentCreateRun(runId, scopeAtStart)) return
      reset()
      onOpenChange(false)
      onCreated(res.id)
    } catch (e) {
      if (!isCurrentCreateRun(runId, scopeAtStart)) return
      toastOperationError(t, e, 'managed.agents.create.failed')
    } finally {
      if (isCurrentCreateRun(runId, scopeAtStart)) {
        setSubmitting(false)
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (v && !currentProjectAllowsWrite()) return
        if (v && !currentManagedScopeIsActive()) return
        if (!v) {
          createRunRef.current += 1
          reset()
        }
        onOpenChange(v)
      }}
    >
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('managed.agents.create.title')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <FormSectionCard
            title={t('managed.agents.basicSettings', '基础配置')}
            description={t('managed.agents.basicSettingsDesc', '设置智能体名称、模型密钥、引擎和系统提示词。')}
          >
          {/* Name */}
          <div>
            <FormFieldLabel required className="mb-1.5">
              {t('managed.agents.name')}
            </FormFieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('managed.agents.create.namePlaceholder')}
            />
          </div>

          {/* Description */}
          <div>
            <FormFieldLabel optional={t('managed.agents.formOptional')} className="mb-1.5">
              {t('managed.agents.description')}
            </FormFieldLabel>
            <textarea
              rows={2}
              className="flex min-h-[64px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('managed.agents.create.descriptionPlaceholder')}
            />
          </div>

          {/* Engine Kind */}
          <div>
            <FormFieldLabel required tooltip={t('managed.agents.engineKindDesc')} className="mb-1.5">
              {t('managed.agents.engineKind')}
            </FormFieldLabel>
            <Select value={engineKind} onValueChange={setEngineKind}>
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

          {/* Secret / API Key */}
          <div>
            <FormFieldLabel optional={t('managed.agents.formOptionalWithDefault')} className="mb-1.5">
              {t('managed.agents.edit.secretRef')}
            </FormFieldLabel>
            {secrets && secrets.length > 0 ? (
              <ModelSecretSelect
                value={effectiveSecretRef}
                secrets={secrets}
                placeholder={t('managed.agents.edit.selectSecret')}
                noneLabel={t('managed.agents.edit.noSelection')}
                searchPlaceholder={t('managed.agents.edit.searchSecret')}
                emptyText={t('managed.agents.edit.noSecretMatch')}
                createLabel={t('managed.agents.edit.createSecret')}
                clearSearchLabel={t('managed.agents.edit.clearSearch')}
                onChange={(value) => {
                  setSecretRef(value)
                  setSecretSelectionCleared(!value)
                }}
                onCreate={() => router.push('/managed/secrets?create=llm')}
              />
            ) : (
              <div className="space-y-2 rounded-md border border-dashed border-border bg-muted/20 p-3">
                <p className="text-sm text-muted-foreground">
                  {t('managed.agents.create.noSecrets')}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => router.push('/managed/secrets?create=llm')}
                >
                  {t('managed.agents.edit.createSecret')}
                </Button>
              </div>
            )}
          </div>

          {/* Default Environment */}
          <div>
            <FormFieldLabel
              optional={t('managed.agents.formOptional')}
              tooltip={t('managed.agents.edit.environmentRefHint')}
              className="mb-1.5"
            >
              {t('managed.agents.edit.environmentRef')}
            </FormFieldLabel>
            {environments && environments.length > 0 ? (
              <SearchableAgentConfigSelect
                value={effectiveEnvironmentRef}
                options={environments.map((env) => ({
                  value: env.id,
                  label: env.name,
                  searchText: env.id,
                }))}
                placeholder={t('managed.agents.edit.selectEnvironment')}
                noneLabel={t('managed.agents.edit.noSelection')}
                searchPlaceholder={t('managed.agents.edit.searchEnvironment')}
                emptyText={t('managed.agents.edit.noEnvironmentMatch')}
                createLabel={t('managed.agents.edit.createEnvironment')}
                clearSearchLabel={t('managed.agents.edit.clearSearch')}
                onChange={setEnvironmentRef}
                onCreate={() => router.push('/managed/environments?create=1')}
              />
            ) : (
              <div className="space-y-2 rounded-md border border-dashed border-border bg-muted/20 p-3">
                <p className="text-sm text-muted-foreground">
                  {t('managed.agents.edit.noEnvironments')}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => router.push('/managed/environments?create=1')}
                >
                  {t('managed.agents.edit.createEnvironment')}
                </Button>
              </div>
            )}
          </div>

          {/* System prompt */}
          <div>
            <FormFieldLabel
              required={systemPromptRequired}
              optional={!systemPromptRequired ? t('managed.agents.formOptional') : undefined}
              className="mb-1.5"
            >
              {t('managed.agents.systemPrompt')}
            </FormFieldLabel>
            <textarea
              className="flex min-h-[160px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder={t('managed.agents.create.systemPromptPlaceholder')}
            />
            <div className="mt-2 flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="radio"
                  name="create_system_prompt_mode"
                  value="append"
                  checked={systemPromptMode === 'append'}
                  onChange={() => setSystemPromptMode('append')}
                  className="accent-primary"
                />
                {t('managed.agents.promptModeAppend', '追加模式')}
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <CircleHelp className="h-3.5 w-3.5 cursor-help text-muted-foreground/60" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-[240px] text-xs">
                      {t('managed.agents.promptModeAppendTooltip', '系统提示追加到引擎（Claude Code）内置提示后面，保留引擎的行为规范和最佳实践指引')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </label>
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="radio"
                  name="create_system_prompt_mode"
                  value="replace"
                  checked={systemPromptMode === 'replace'}
                  onChange={() => setSystemPromptMode('replace')}
                  className="accent-primary"
                />
                {t('managed.agents.promptModeReplace', '替换模式')}
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <CircleHelp className="h-3.5 w-3.5 cursor-help text-muted-foreground/60" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-[240px] text-xs">
                      {t('managed.agents.promptModeReplaceTooltip', '完全替换引擎内置提示，由你的系统提示全权控制 Agent 行为。工具（Bash/文件读写等）仍可正常使用')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </label>
            </div>
          </div>

          <hr className="border-dashed" />

          </FormSectionCard>

          <AdvancedSection
            open={showAdvanced}
            onOpenChange={setShowAdvanced}
            title={t('managed.agents.create.advancedOptions', '高级选项')}
            summary={t('managed.agents.create.advancedSummary', 'MCP、工具、Skills')}
          >
          {/* Tools */}
          <div className="order-3">
            <label className="mb-3 block text-sm font-medium text-foreground">
              {t('managed.agents.edit.tools')}
            </label>
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
            <div className="mt-4">
              <label className="mb-1.5 block text-sm font-medium text-foreground">
                {t('managed.agents.edit.permissionMode')}
                <FieldHelp text={t('managed.agents.edit.permissionModeHint', '控制 Agent 使用工具（如执行命令、写文件）时是否需要人工确认。「跳过确认」允许 Agent 自主执行所有操作。')} />
              </label>
              <select
                className="flex w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                value={permissionMode}
                onChange={(e) => setPermissionMode(e.target.value)}
              >
                {PERMISSION_MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {t(m.labelKey)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <hr className="order-4 border-dashed" />

          {/* MCP Servers */}
          <div className="order-1">
            <div className="mb-3 flex items-center justify-between">
              <label className="text-sm font-medium text-foreground">
                {t('managed.agents.edit.mcpServers')}
              </label>
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
              <div key={i} className="mb-2 flex items-center gap-2 text-sm">
                <span className="font-medium">{m.name}</span>
                <span className="flex-1 truncate text-muted-foreground">{m.url}</span>
                <select
                  value={m.policy || 'always_ask'}
                  onChange={(e) => setMcpPolicy(i, e.target.value as 'always_allow' | 'always_ask')}
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
              <div className="mt-2 flex items-end gap-2">
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
          </div>

          <hr className="order-2 border-dashed" />

          {/* Skills */}
          <div className="order-5">
            <label className="mb-3 block text-sm font-medium text-foreground">
              {t('managed.agents.edit.skills')}
            </label>
            {!skills || skills.length === 0 ? (
              <p className="py-2 text-center text-sm text-muted-foreground">
                {t('managed.agents.create.noSkills')}{' '}
                <a href="/managed/skills" className="text-emerald-500 hover:underline">
                  {t('managed.agents.create.goCreateSkill')} &rarr;
                </a>
              </p>
            ) : (
              <div className="space-y-2">
                {skills.map((skill) => {
                  const isSelected = effectiveSelectedSkillIds.has(skill.id)
                  const unavailableReason = skillUnavailableReason(skill)
                  const unavailable = unavailableReason !== null
                  const toggle = () => {
                    if (unavailable) return
                    setSelectedSkillIds((prev) => {
                      const next = new Set(prev)
                      if (next.has(skill.id)) next.delete(skill.id)
                      else next.add(skill.id)
                      return next
                    })
                  }
                  return (
                    <div key={skill.id} className="flex items-center gap-2">
                      <label
                        className={`flex min-w-0 flex-1 select-none items-center gap-2 ${
                          unavailable ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                        }`}
                        title={
                          unavailable
                            ? t('managed.agents.create.skillUnavailable', {
                                reason: unavailableReason,
                                defaultValue: `Skill is not runtime-ready: ${unavailableReason}`,
                              })
                            : undefined
                        }
                      >
                        <span
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                            isSelected
                              ? 'border-emerald-400 bg-emerald-400 text-white'
                              : 'border-border bg-background'
                          }`}
                          onClick={toggle}
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
                        <span className="truncate text-sm text-foreground" onClick={toggle}>
                          {skill.name || skill.id}
                        </span>
                        {unavailable && (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] text-amber-900 dark:bg-amber-900/50 dark:text-amber-100">
                            {unavailableReason}
                          </span>
                        )}
                      </label>
                      {isSelected && (
                        <SkillVersionSelect
                          skillId={skill.id}
                          value={effectiveSkillVersions[skill.id] || 'latest'}
                          onChange={(v) => setSkillVersions((prev) => ({ ...prev, [skill.id]: v }))}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          </AdvancedSection>
        </div>

        <FormActionBar>
          <Button
            variant="outline"
            onClick={() => {
              reset()
              onOpenChange(false)
            }}
          >
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !name.trim() || !systemPromptValid}>
            {submitting ? t('managed.agents.create.creating') : t('managed.agents.create.submit')}
          </Button>
        </FormActionBar>
      </DialogContent>
    </Dialog>
  )
}
