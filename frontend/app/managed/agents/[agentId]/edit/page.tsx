'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import type { Agent, McpServer, AgentSkillRef } from '@/types/managed'
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
import { FieldHelp, PageHeader } from '@/components/managed/shared'
import { Plus, Trash2 } from 'lucide-react'

const BUILTIN_TOOLS = [
  'Bash', 'Read', 'Write', 'Edit',
  'Glob', 'Grep', 'WebFetch', 'WebSearch',
]

const PERMISSION_MODES = [
  { value: 'bypassPermissions', labelKey: 'agents.edit.permBypass' },
  { value: 'default', labelKey: 'agents.edit.permAsk' },
  { value: 'deny', labelKey: 'agents.edit.permDeny' },
]

interface McpServerEntry {
  name: string
  url: string
}

interface EnvVarEntry {
  key: string
  value: string
}

interface ManagedListResponse<T> {
  data: T[]
}

interface SkillListItem {
  id: string
  name?: string
  display_title?: string
}

interface EnvironmentListItem {
  id: string
  name: string
}

export default function AgentEditPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = React.use(params)
  const router = useRouter()
  const queryClient = useQueryClient()
  const { t } = useTranslation()

  // ── Fetch agent ──
  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => managedGet<Agent>(`/agents/${stripIdPrefix(agentId)}`),
    enabled: !!agentId,
  })

  // ── Fetch secrets ──
  const { data: secretsRes } = useQuery({
    queryKey: ['secrets'],
    queryFn: () => managedGet<{ data: { name: string }[] }>('/secrets'),
  })
  const secrets = secretsRes?.data

  // ── Fetch skills ──
  const { data: skills } = useQuery({
    queryKey: ['skills'],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<SkillListItem>>('/skills')
      return res.data || []
    },
  })

  // ── Fetch environments ──
  const { data: environments } = useQuery({
    queryKey: ['environments'],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<EnvironmentListItem>>('/environments')
      return res.data || []
    },
  })

  // ── Basic info state ──
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [engineKind, setEngineKind] = useState('claude')
  const [systemPrompt, setSystemPrompt] = useState('')

  // ── MCP servers state ──
  const [mcpServers, setMcpServers] = useState<McpServerEntry[]>([])
  const [showMcpForm, setShowMcpForm] = useState(false)
  const [mcpName, setMcpName] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')

  // ── Tools state ──
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set(BUILTIN_TOOLS))

  // ── Skills state ──
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set())

  // ── Secret ref ──
  const [secretRef, setSecretRef] = useState('')

  // ── Environment ref ──
  const [environmentRef, setEnvironmentRef] = useState('')

  // ── Permission mode ──
  const [permissionMode, setPermissionMode] = useState('bypassPermissions')

  // ── Environment variables ──
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([])

  // ── Populate state from agent data ──
  useEffect(() => {
    if (!agent) return

    setName(agent.name)
    setDescription(agent.description || '')
    setEngineKind(agent.engine_kind || 'claude')
    setSystemPrompt(agent.system || agent.system_prompt || '')

    // MCP servers
    if (agent.mcp_servers && agent.mcp_servers.length > 0) {
      setMcpServers(agent.mcp_servers.map((m) => ({ name: m.name, url: m.url })))
    }

    // Tools
    if (agent.tools) {
      const toolset = agent.tools.find((t) => t.type === 'agent_toolset_20260401')
      if (toolset && toolset.type === 'agent_toolset_20260401') {
        const enabled = new Set<string>()
        const configs = toolset.configs || []
        for (const cfg of configs) {
          if (cfg.enabled !== false) {
            enabled.add(cfg.name)
          }
        }
        // If no configs, assume all enabled
        if (configs.length === 0) {
          BUILTIN_TOOLS.forEach((t) => enabled.add(t))
        }
        setEnabledTools(enabled)

        // Permission mode from default_config
        const dc = toolset.default_config
        if (dc?.permission_policy?.type === 'always_ask') {
          setPermissionMode('default')
        } else {
          setPermissionMode('bypassPermissions')
        }
      }
    }

    // Skills
    if (agent.skills && agent.skills.length > 0) {
      setSelectedSkillIds(new Set(agent.skills.map((s) => s.skill_id)))
    }

    // Secret ref
    if (agent.secret_ref) {
      setSecretRef(agent.secret_ref)
    }

    // Environment ref
    if (agent.environment_ref) {
      setEnvironmentRef(agent.environment_ref)
    }

    // Env vars
    if (agent.env && Object.keys(agent.env).length > 0) {
      setEnvVars(Object.entries(agent.env).map(([key, value]) => ({ key, value })))
    }
  }, [agent])

  // ── Toggle tool ──
  const toggleTool = (tool: string) => {
    setEnabledTools((prev) => {
      const next = new Set(prev)
      if (next.has(tool)) next.delete(tool)
      else next.add(tool)
      return next
    })
  }

  // ── MCP server helpers ──
  const addMcpServer = () => {
    if (!mcpName.trim() || !mcpUrl.trim()) return
    // URL scheme validation
    const { validateUrlScheme } = require('@/lib/utils/url-validation')
    const urlError = validateUrlScheme(mcpUrl.trim())
    if (urlError) {
      toastOperationError(t, new Error(urlError), 'common.error')
      return
    }
    setMcpServers((prev) => [...prev, { name: mcpName.trim(), url: mcpUrl.trim() }])
    setMcpName('')
    setMcpUrl('')
    setShowMcpForm(false)
  }

  const removeMcpServer = (idx: number) => {
    setMcpServers((prev) => prev.filter((_, i) => i !== idx))
  }

  // ── Skill toggle ──
  const toggleSkill = (skillId: string) => {
    setSelectedSkillIds((prev) => {
      const next = new Set(prev)
      if (next.has(skillId)) next.delete(skillId)
      else next.add(skillId)
      return next
    })
  }

  // ── Env var helpers ──
  const addEnvVar = () => {
    setEnvVars((prev) => [...prev, { key: '', value: '' }])
  }

  const updateEnvVar = (idx: number, field: 'key' | 'value', val: string) => {
    setEnvVars((prev) => prev.map((e, i) => (i === idx ? { ...e, [field]: val } : e)))
  }

  const removeEnvVar = (idx: number) => {
    setEnvVars((prev) => prev.filter((_, i) => i !== idx))
  }

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
      })
    }
    return tools
  }

  // ── Build env vars payload ──
  const buildEnvPayload = (): Record<string, string> => {
    const result: Record<string, string> = {}
    for (const entry of envVars) {
      if (entry.key.trim()) {
        result[entry.key.trim()] = entry.value
      }
    }
    return result
  }

  // ── Save mutation ──
  const mutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        version: agent!.version || 1,
        name,
        description: description || null,
        engine_kind: engineKind,
        system: systemPrompt || null,
        mcp_servers: mcpServers
          .filter((s) => s.name && s.url)
          .map((m) => ({ type: 'url', name: m.name, url: m.url })),
        tools: buildToolsPayload(),
        skills: Array.from(selectedSkillIds).map((id) => ({
          type: 'custom' as const,
          skill_id: id,
          version: 'latest',
        })),
        secret_ref: secretRef || undefined,
        environment_ref: environmentRef || undefined,
        env: buildEnvPayload(),
      }
      return managedPost(`/agents/${stripIdPrefix(agentId)}`, body)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', agentId] })
      router.push(`/managed/agents/${agentId}`)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  if (isLoading || !agent) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!agent.archived_at

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

        {/* ───────── Basic Info ───────── */}
        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground border-b border-border pb-2">
            {t('agents.edit.basicInfo')}
          </h3>

          <div>
            <label className="text-sm font-medium text-foreground block mb-1.5">{t('managed.agents.name')}</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div>
            <label className="text-sm font-medium text-foreground block mb-1.5">{t('managed.agents.description')}</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('managed.agents.descriptionPlaceholder')}
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <label className="text-sm font-medium text-foreground">{t('managed.agents.engineKind')}</label>
              <FieldHelp text={t('managed.agents.engineKindDesc')} />
            </div>
            <Select value={engineKind} onValueChange={setEngineKind}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="claude">{t('managed.agents.engineClaude')}</SelectItem>
                <SelectItem value="codex">{t('managed.agents.engineCodex')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="text-sm font-medium text-foreground block mb-1.5">{t('managed.agents.systemPrompt')}</label>
            <textarea
              className="flex w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring min-h-[200px] resize-y"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder={t('managed.agents.systemPromptPlaceholder')}
            />
          </div>
        </section>

        {/* ───────── MCP Servers ───────── */}
        <section className="space-y-3">
          <div className="flex items-center justify-between border-b border-border pb-2">
            <h3 className="text-sm font-semibold text-foreground">
              {t('agents.edit.mcpServers')}
            </h3>
            <button
              type="button"
              onClick={() => setShowMcpForm(true)}
              className="flex h-6 w-6 items-center justify-center rounded border border-border hover:bg-accent transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {mcpServers.length === 0 && !showMcpForm && (
            <p className="text-sm text-muted-foreground text-center py-2">
              {t('managed.agents.create.noMcpServers')}
            </p>
          )}

          {mcpServers.map((m, i) => (
            <div key={i} className="flex items-center gap-2 text-sm">
              <span className="font-medium">{m.name}</span>
              <span className="text-muted-foreground truncate flex-1">{m.url}</span>
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
          <h3 className="text-sm font-semibold text-foreground border-b border-border pb-2">
            {t('agents.edit.tools')}
          </h3>
          <div className="grid grid-cols-4 gap-3">
            {BUILTIN_TOOLS.map((tool) => (
              <label key={tool} className="flex items-center gap-2 cursor-pointer select-none">
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded border transition-colors ${
                    enabledTools.has(tool)
                      ? 'bg-emerald-400 border-emerald-400 text-white'
                      : 'border-border bg-background'
                  }`}
                  onClick={() => toggleTool(tool)}
                >
                  {enabledTools.has(tool) && (
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
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
        </section>

        {/* ───────── Skills ───────── */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-foreground border-b border-border pb-2">
            {t('agents.edit.skills')}
          </h3>
          {(!skills || skills.length === 0) ? (
            <p className="text-sm text-muted-foreground text-center py-2">
              {t('managed.agents.create.noSkills')}{' '}
              <a href="/managed/skills" className="text-emerald-500 hover:underline">
                {t('managed.agents.create.goCreateSkill')} &rarr;
              </a>
            </p>
          ) : (
            <div className="space-y-2">
              {skills.map((skill) => (
                <label key={skill.id} className="flex items-center gap-2 cursor-pointer select-none">
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded border transition-colors ${
                      selectedSkillIds.has(skill.id)
                        ? 'bg-emerald-400 border-emerald-400 text-white'
                        : 'border-border bg-background'
                    }`}
                    onClick={() => toggleSkill(skill.id)}
                  >
                    {selectedSkillIds.has(skill.id) && (
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span className="text-sm text-foreground" onClick={() => toggleSkill(skill.id)}>
                    {skill.display_title || skill.name || skill.id}
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        {/* ───────── Secret Reference ───────── */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-foreground border-b border-border pb-2">
            {t('agents.edit.secretRef')}
          </h3>
          {secrets && secrets.length > 0 ? (
            <Select value={secretRef || '__none__'} onValueChange={(v) => setSecretRef(v === '__none__' ? '' : v)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t('agents.edit.selectSecret')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">{t('agents.edit.noSelection')}</SelectItem>
                {secrets.map((s) => (
                  <SelectItem key={s.name} value={s.name}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-sm text-muted-foreground">{t('managed.agents.create.noSecrets')}</p>
          )}
        </section>

        {/* ───────── Environment Reference ───────── */}
        <section className="space-y-3">
          <div className="flex items-center gap-1.5 border-b border-border pb-2">
            <h3 className="text-sm font-semibold text-foreground">{t('agents.edit.environmentRef')}</h3>
            <FieldHelp text={t('agents.edit.environmentRefHint')} />
          </div>
          {environments && environments.length > 0 ? (
            <Select value={environmentRef || '__none__'} onValueChange={(v) => setEnvironmentRef(v === '__none__' ? '' : v)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t('agents.edit.selectEnvironment')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">{t('agents.edit.noSelection')}</SelectItem>
                {environments.map((env) => (
                  <SelectItem key={env.id} value={env.id}>
                    {env.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-sm text-muted-foreground">{t('agents.edit.noEnvironments')}</p>
          )}
        </section>

        {/* ───────── Environment Variables ───────── */}
        <section className="space-y-3">
          <div className="flex items-center justify-between border-b border-border pb-2">
            <h3 className="text-sm font-semibold text-foreground">
              {t('agents.edit.envVars')}
            </h3>
            <button
              type="button"
              onClick={addEnvVar}
              className="flex h-6 w-6 items-center justify-center rounded border border-border hover:bg-accent transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {envVars.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-2">
              {t('agents.edit.noEnvVars')}
            </p>
          )}

          {envVars.map((entry, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                className="flex-1 text-sm"
                placeholder={t('agents.edit.envKeyPlaceholder')}
                value={entry.key}
                onChange={(e) => updateEnvVar(i, 'key', e.target.value)}
              />
              <Input
                className="flex-[2] text-sm"
                placeholder={t('agents.edit.envValuePlaceholder')}
                value={entry.value}
                onChange={(e) => updateEnvVar(i, 'value', e.target.value)}
              />
              <button
                type="button"
                onClick={() => removeEnvVar(i)}
                className="text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </section>

        {/* ───────── Action buttons ───────── */}
        <div className="flex items-center gap-3 pt-2 border-t border-border">
          <Button onClick={() => mutation.mutate()} disabled={isArchived || mutation.isPending}>
            {mutation.isPending ? t('managed.agents.saving') : t('managed.agents.saveChanges')}
          </Button>
          <Button variant="outline" onClick={() => router.push(`/managed/agents/${agentId}`)}>
            {t('common.cancel')}
          </Button>
        </div>
      </div>
    </div>
  )
}
