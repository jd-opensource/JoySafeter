'use client'

import { useState, useEffect } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { managedGet, managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { FieldHelp, SkillVersionSelect } from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from '@/components/ui/select'

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

interface EnvVarEntry {
  key: string
  value: string
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

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [engineKind, setEngineKind] = useState('claude')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set(BUILTIN_TOOLS))
  const [mcpServers, setMcpServers] = useState<McpServerEntry[]>([])
  const [showMcpForm, setShowMcpForm] = useState(false)
  const [mcpName, setMcpName] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')
  const [secretRef, setSecretRef] = useState('')
  const [environmentRef, setEnvironmentRef] = useState('')
  const [permissionMode, setPermissionMode] = useState('bypassPermissions')
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set())
  /** skill_id → chosen version keyword ("latest", "draft") or semver string. */
  const [skillVersions, setSkillVersions] = useState<Record<string, string>>({})
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([])
  const [submitting, setSubmitting] = useState(false)

  const { data: secretsRes } = useQuery({
    queryKey: ['secrets'],
    queryFn: () => managedGet<{ data: { name: string }[] }>('/secrets'),
    enabled: open,
  })
  const secrets = secretsRes?.data

  const { data: skills } = useQuery({
    queryKey: ['skills'],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<SkillListItem>>('/skills')
      // Agents can only reference *published* skills — hide draft-only
      // skills (no published version yet) from the picker entirely.
      return (res.data || []).filter((s) => !!s.latest_version)
    },
    enabled: open,
  })

  const { data: environments } = useQuery({
    queryKey: ['environments'],
    queryFn: async () => {
      const res = await managedGet<ManagedListResponse<EnvironmentListItem>>('/environments')
      return res.data || []
    },
    enabled: open,
  })

  useEffect(() => {
    if (secrets && secrets.length > 0 && !secretRef) {
      setSecretRef(secrets[0].name)
    }
  }, [secrets, secretRef])

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
    setEnvironmentRef('')
    setPermissionMode('bypassPermissions')
    setSelectedSkillIds(new Set())
    setSkillVersions({})
    setEnvVars([])
    setSubmitting(false)
  }

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
    // Validate URL scheme
    const { validateUrlScheme } = require('@/lib/utils/url-validation')
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

  const addEnvVar = () => {
    setEnvVars((prev) => [...prev, { key: '', value: '' }])
  }

  const updateEnvVar = (idx: number, field: 'key' | 'value', val: string) => {
    setEnvVars((prev) => prev.map((e, i) => (i === idx ? { ...e, [field]: val } : e)))
  }

  const removeEnvVar = (idx: number) => {
    setEnvVars((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleSubmit = async () => {
    if (!name.trim()) return
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

      // Build env payload
      const envPayload: Record<string, string> = {}
      for (const entry of envVars) {
        if (entry.key.trim()) {
          envPayload[entry.key.trim()] = entry.value
        }
      }

      const res = await managedPost<{ id: string }>('/agents', {
        name: name.trim(),
        description: description.trim() || null,
        engine_kind: engineKind,
        system_prompt: systemPrompt || null,
        secret_ref: secretRef || undefined,
        environment_ref: environmentRef || undefined,
        tools,
        mcp_servers: mcpServers.map((m) => ({ type: 'url', name: m.name, url: m.url })),
        skill_ids: Array.from(selectedSkillIds),
        skills: Array.from(selectedSkillIds).map((id) => ({
          type: 'custom' as const,
          skill_id: id,
          version: skillVersions[id] || 'latest',
        })),
        env: Object.keys(envPayload).length > 0 ? envPayload : undefined,
      })
      reset()
      onOpenChange(false)
      onCreated(res.id)
    } catch (e) {
      toastOperationError(t, e, 'managed.agents.create.failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) {
          reset()
        }
        onOpenChange(v)
      }}
    >
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('managed.agents.create.title')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-6 py-2">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">
              {t('managed.agents.name')}
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('managed.agents.create.namePlaceholder')}
            />
          </div>

          {/* Description */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">
              {t('managed.agents.description')}
            </label>
            <textarea
              className="flex min-h-[100px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('managed.agents.create.descriptionPlaceholder')}
            />
          </div>

          {/* Engine Kind */}
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <label className="text-sm font-medium text-foreground">
                {t('managed.agents.engineKind')}
              </label>
              <FieldHelp text={t('managed.agents.engineKindDesc')} />
            </div>
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
            <label className="mb-1.5 block text-sm font-medium text-foreground">
              {t('managed.agents.edit.secretRef')}
            </label>
            {secrets && secrets.length > 0 ? (
              <Select
                value={secretRef || '__none__'}
                onValueChange={(v) => setSecretRef(v === '__none__' ? '' : v)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t('managed.agents.edit.noSelection')}</SelectItem>
                  {secrets.map((s) => (
                    <SelectItem key={s.name} value={s.name}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t('managed.agents.create.noSecrets')}
              </p>
            )}
          </div>

          {/* Default Environment */}
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <label className="text-sm font-medium text-foreground">
                {t('managed.agents.edit.environmentRef')}
              </label>
              <FieldHelp text={t('managed.agents.edit.environmentRefHint')} />
            </div>
            {environments && environments.length > 0 ? (
              <Select
                value={environmentRef || '__none__'}
                onValueChange={(v) => setEnvironmentRef(v === '__none__' ? '' : v)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t('managed.agents.edit.selectEnvironment')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t('managed.agents.edit.noSelection')}</SelectItem>
                  {environments.map((env) => (
                    <SelectItem key={env.id} value={env.id}>
                      {env.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t('managed.agents.edit.noEnvironments')}
              </p>
            )}
          </div>

          {/* System prompt */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">
              {t('managed.agents.systemPrompt')}
            </label>
            <textarea
              className="flex min-h-[160px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder={t('managed.agents.create.systemPromptPlaceholder')}
            />
          </div>

          <hr className="border-dashed" />

          {/* Tools */}
          <div>
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

          <hr className="border-dashed" />

          {/* MCP Servers */}
          <div>
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

          <hr className="border-dashed" />

          {/* Skills */}
          <div>
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
                  const isSelected = selectedSkillIds.has(skill.id)
                  const toggle = () => {
                    setSelectedSkillIds((prev) => {
                      const next = new Set(prev)
                      if (next.has(skill.id)) next.delete(skill.id)
                      else next.add(skill.id)
                      return next
                    })
                  }
                  return (
                    <div key={skill.id} className="flex items-center gap-2">
                      <label className="flex min-w-0 flex-1 cursor-pointer select-none items-center gap-2">
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
                      </label>
                      {isSelected && (
                        <SkillVersionSelect
                          skillId={skill.id}
                          value={skillVersions[skill.id] || 'latest'}
                          onChange={(v) => setSkillVersions((prev) => ({ ...prev, [skill.id]: v }))}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              reset()
              onOpenChange(false)
            }}
          >
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !name.trim()}>
            {submitting ? t('managed.agents.create.creating') : t('managed.agents.create.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
