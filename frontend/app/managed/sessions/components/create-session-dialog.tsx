'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, ExternalLink, X, Check, FileIcon, GitBranch, Search, ChevronDown } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { AdvancedSection, FormActionBar, FormFieldLabel, FormSectionCard } from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { managedGet, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourceId } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useProjectStore } from '@/stores/managed/project-store'
import type { Agent, Environment, Vault, FileRecord, PaginatedResponse } from '@/types/managed'

interface SelectedFile {
  file_id: string
  filename: string
  mount_path: string
}

interface SelectedRepo {
  key: string
  url: string
  branch: string
  mount_path: string
  authorization_token: string
}

interface MemoryStoreOption {
  id: string
  name: string
  description?: string
  archived_at?: string | null
}

interface CreateSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (sessionId: string) => void
}

interface CreateSessionMutationInput {
  body: Record<string, unknown>
  runId: number
  scope: ManagedRequestScope
}

const sessionSelectTriggerClassName = 'h-10 text-sm data-[placeholder]:text-muted-foreground'
const customSelectTriggerClassName =
  'flex h-10 w-full items-center justify-between rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2 text-sm text-[var(--text-primary)] shadow-sm ring-offset-background transition-all focus:border-[var(--brand-400)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-100)] disabled:cursor-not-allowed disabled:opacity-50'

export function CreateSessionDialog({ open, onOpenChange, onCreated }: CreateSessionDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const createRunRef = useRef(0)
  const vaultDropdownRef = useRef<HTMLDivElement | null>(null)
  const fileDropdownRef = useRef<HTMLDivElement | null>(null)
  const memoryStoreDropdownRef = useRef<HTMLDivElement | null>(null)

  const [title, setTitle] = useState('')
  const [agentId, setAgentId] = useState('')
  const [agentSearch, setAgentSearch] = useState('')
  const [envId, setEnvId] = useState('')
  const [envSearch, setEnvSearch] = useState('')
  const [selectedVaultIds, setSelectedVaultIds] = useState<string[]>([])
  const [vaultSearch, setVaultSearch] = useState('')
  const [showVaultDropdown, setShowVaultDropdown] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([])
  const [fileSearch, setFileSearch] = useState('')
  const [showFileDropdown, setShowFileDropdown] = useState(false)
  const [selectedRepos, setSelectedRepos] = useState<SelectedRepo[]>([])
  const [selectedMemoryStores, setSelectedMemoryStores] = useState<string[]>([])
  const [memoryStoreSearch, setMemoryStoreSearch] = useState('')
  const [showMemoryStoreDropdown, setShowMemoryStoreDropdown] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents-for-session', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Agent>>(
        '/agents',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: open && hasManagedRequestScope(managedScope),
  })

  const { data: environments = [] } = useQuery({
    queryKey: ['envs-for-session', managedScope.key],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Environment>>(
        '/environments',
        managedRequestOptions(managedScope),
      )
      return res.data || []
    },
    enabled: open && hasManagedRequestScope(managedScope),
  })

  const { data: vaultsRes } = useQuery({
    queryKey: ['vaults-for-session', managedScope.key],
    queryFn: () => managedGet<{ data: Vault[] }>('/vaults', managedRequestOptions(managedScope)),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const vaults = useMemo(() => vaultsRes?.data || [], [vaultsRes])

  const { data: filesResp } = useQuery({
    queryKey: ['files-for-session', managedScope.key],
    queryFn: () =>
      managedGet<{ data: FileRecord[] }>('/files?limit=100', managedRequestOptions(managedScope)),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const files = useMemo(() => {
    if (!filesResp) return []
    return filesResp.data || []
  }, [filesResp])

  const { data: memoryStoresResp } = useQuery({
    queryKey: ['memory-stores-for-session', managedScope.key],
    queryFn: () =>
      managedGet<{ data: MemoryStoreOption[] }>(
        '/memory_stores?limit=100',
        managedRequestOptions(managedScope),
      ),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const memoryStores = useMemo(() => {
    const stores = memoryStoresResp?.data || []
    return stores.filter((store) => !store.archived_at)
  }, [memoryStoresResp])
  const activeAgents = useMemo(() => agents.filter((a) => !a.archived_at), [agents])
  // Group the agent dropdown by engine so picking one is less of a flat scroll.
  // Stable order: Claude Code → Codex → Native → anything else.
  // Filters by ``agentSearch`` (case-insensitive substring on the agent name
  // OR the engine label, so typing "claude" narrows to that group).
  const agentGroups = useMemo(() => {
    const labelFor = (k?: string | null) => {
      switch (k) {
        case 'claude':
        case 'claude_code':
          return 'Claude Code'
        case 'codex':
          return 'Codex'
        case 'native':
          return 'Native'
        default:
          return k || 'Other'
      }
    }
    const order = ['Claude Code', 'Codex', 'Native']
    const q = agentSearch.trim().toLowerCase()
    const buckets = new Map<string, typeof activeAgents>()
    for (const a of activeAgents) {
      const label = labelFor(a.engine_kind)
      if (q && !a.name.toLowerCase().includes(q) && !label.toLowerCase().includes(q)) continue
      if (!buckets.has(label)) buckets.set(label, [])
      buckets.get(label)!.push(a)
    }
    return Array.from(buckets.entries()).sort(
      ([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99),
    )
  }, [activeAgents, agentSearch])
  const activeEnvs = useMemo(() => environments.filter((e) => !e.archived_at), [environments])
  const activeVaults = useMemo(() => vaults.filter((v) => !v.archived_at), [vaults])
  const filteredEnvs = useMemo(() => {
    const q = envSearch.trim().toLowerCase()
    if (!q) return activeEnvs
    return activeEnvs.filter((env) => `${env.name} ${env.id}`.toLowerCase().includes(q))
  }, [activeEnvs, envSearch])
  const filteredVaults = useMemo(() => {
    const q = vaultSearch.trim().toLowerCase()
    if (!q) return activeVaults
    return activeVaults.filter((vault) => `${vault.name} ${vault.id}`.toLowerCase().includes(q))
  }, [activeVaults, vaultSearch])
  const effectiveAgentId = useMemo(
    () => (agentId && activeAgents.some((agent) => agent.id === agentId) ? agentId : ''),
    [activeAgents, agentId],
  )
  const effectiveEnvId = useMemo(
    () => (envId && activeEnvs.some((environment) => environment.id === envId) ? envId : ''),
    [activeEnvs, envId],
  )
  const effectiveSelectedVaultIds = useMemo(() => {
    const vaultIds = new Set(activeVaults.map((vault) => vault.id))
    return selectedVaultIds.filter((id) => vaultIds.has(id))
  }, [activeVaults, selectedVaultIds])
  const effectiveSelectedFiles = useMemo(() => {
    const fileIds = new Set(files.map((file) => file.id))
    return selectedFiles.filter((file) => fileIds.has(file.file_id))
  }, [files, selectedFiles])
  const effectiveSelectedMemoryStores = useMemo(() => {
    const storeIds = new Set(memoryStores.map((store) => store.id))
    return selectedMemoryStores.filter((id) => storeIds.has(id))
  }, [memoryStores, selectedMemoryStores])
  const availableMemoryStores = useMemo(
    () => memoryStores.filter((store) => !effectiveSelectedMemoryStores.includes(store.id)),
    [effectiveSelectedMemoryStores, memoryStores],
  )
  const filteredAvailableMemoryStores = useMemo(() => {
    const q = memoryStoreSearch.trim().toLowerCase()
    if (!q) return availableMemoryStores
    return availableMemoryStores.filter((store) => `${store.name} ${store.id}`.toLowerCase().includes(q))
  }, [availableMemoryStores, memoryStoreSearch])
  const selectedAgent = useMemo(
    () => activeAgents.find((agent) => agent.id === effectiveAgentId),
    [activeAgents, effectiveAgentId],
  )
  const selectedAgentDefaultEnv = useMemo(() => {
    const ref = selectedAgent?.environment_ref
    if (!ref) return null
    return (
      activeEnvs.find((env) => env.id === ref || stripIdPrefix(env.id) === stripIdPrefix(ref)) ||
      null
    )
  }, [activeEnvs, selectedAgent])

  const availableFiles = useMemo(
    () => files.filter((f) => !effectiveSelectedFiles.some((sf) => sf.file_id === f.id)),
    [effectiveSelectedFiles, files],
  )
  const filteredAvailableFiles = useMemo(() => {
    const q = fileSearch.trim().toLowerCase()
    if (!q) return availableFiles
    return availableFiles.filter((file) => `${file.filename} ${file.id}`.toLowerCase().includes(q))
  }, [availableFiles, fileSearch])

  const resetForm = () => {
    setTitle('')
    setAgentId('')
    setAgentSearch('')
    setEnvId('')
    setEnvSearch('')
    setSelectedVaultIds([])
    setVaultSearch('')
    setShowVaultDropdown(false)
    setSelectedFiles([])
    setFileSearch('')
    setShowFileDropdown(false)
    setSelectedRepos([])
    setSelectedMemoryStores([])
    setMemoryStoreSearch('')
    setShowMemoryStoreDropdown(false)
    setShowAdvanced(false)
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentCreateRun = (runId: number, scope: string) =>
    createRunRef.current === runId &&
    managedScopeRef.current === scope &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const createMutation = useMutation({
    mutationFn: async ({ body, scope }: CreateSessionMutationInput) => {
      if (!currentManagedScopeIsActive(scope.key)) {
        throw new Error('stale managed scope')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project session create ignored')
      }
      return managedPost<{ id: string }>('/sessions', body, managedRequestOptions(scope))
    },
    onSuccess: (res, input) => {
      if (!isCurrentCreateRun(input.runId, input.scope.key)) return
      onOpenChange(false)
      resetForm()
      if (onCreated) {
        onCreated(res.id)
      } else {
        router.push(`/managed/sessions/${res.id}`)
      }
    },
    onError: (error, input) => {
      if (!isCurrentCreateRun(input.runId, input.scope.key)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    createMutation.reset()
    resetForm()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [managedScope.key])

  useEffect(
    () => () => {
      createRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (!open || (!showVaultDropdown && !showFileDropdown && !showMemoryStoreDropdown)) return
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null
      if (!target) return
      const element = target instanceof Element ? target : target.parentElement
      const isInteractiveTarget = Boolean(
        element?.closest('button,input,textarea,select,a,[role="option"],[data-dropdown-interactive="true"]'),
      )
      const insideDropdown = Boolean(
        vaultDropdownRef.current?.contains(target) ||
          fileDropdownRef.current?.contains(target) ||
          memoryStoreDropdownRef.current?.contains(target),
      )
      if (insideDropdown && isInteractiveTarget) return
      setShowVaultDropdown(false)
      setShowFileDropdown(false)
      setShowMemoryStoreDropdown(false)
    }
    document.addEventListener('pointerdown', handlePointerDown, true)
    return () => document.removeEventListener('pointerdown', handlePointerDown, true)
  }, [open, showFileDropdown, showMemoryStoreDropdown, showVaultDropdown])

  const buildCreatePayload = (scope = managedScopeRef.current) => {
    if (!currentManagedScopeIsActive(scope)) return null
    if (!currentProjectAllowsWrite()) return null
    const currentAgents = queryClient.getQueryData<Agent[]>(['agents-for-session', scope]) ?? agents
    const currentEnvironments =
      queryClient.getQueryData<Environment[]>(['envs-for-session', scope]) ?? environments
    const currentVaults =
      queryClient.getQueryData<{ data?: Vault[] }>(['vaults-for-session', scope])?.data ?? vaults
    const currentFiles =
      queryClient.getQueryData<{ data?: FileRecord[] }>(['files-for-session', scope])?.data ?? files
    const currentMemoryStores =
      queryClient.getQueryData<{ data?: MemoryStoreOption[] }>(['memory-stores-for-session', scope])
        ?.data ?? memoryStores
    const currentActiveAgents = currentAgents.filter((agent) => !agent.archived_at)
    const currentActiveEnvs = currentEnvironments.filter((environment) => !environment.archived_at)
    const currentActiveVaults = currentVaults.filter((vault) => !vault.archived_at)
    const currentActiveMemoryStores = currentMemoryStores.filter((store) => !store.archived_at)
    const currentAgentId =
      agentId && currentActiveAgents.some((agent) => agent.id === agentId) ? agentId : ''
    if (!currentAgentId) return null
    const currentEnvId =
      envId && currentActiveEnvs.some((environment) => environment.id === envId) ? envId : ''
    const currentVaultIds = new Set(currentActiveVaults.map((vault) => vault.id))
    const currentSelectedVaultIds = selectedVaultIds.filter((id) => currentVaultIds.has(id))
    const currentFileIds = new Set(currentFiles.map((file) => file.id))
    const currentSelectedFiles = selectedFiles.filter((file) => currentFileIds.has(file.file_id))
    const currentMemoryStoreIds = new Set(currentActiveMemoryStores.map((store) => store.id))
    const currentSelectedMemoryStores = selectedMemoryStores.filter((id) =>
      currentMemoryStoreIds.has(id),
    )
    const body: Record<string, unknown> = {
      agent: apiResourceId(currentAgentId),
    }
    if (title.trim()) body.title = title.trim()
    if (currentEnvId) body.environment_id = apiResourceId(currentEnvId)
    if (currentSelectedVaultIds.length > 0) {
      body.vault_ids = currentSelectedVaultIds.map(apiResourceId)
    }
    if (currentSelectedFiles.length > 0) {
      body.file_resources = currentSelectedFiles.map((f) => ({
        type: 'file',
        file_id: f.file_id,
        mount_path: f.mount_path,
      }))
    }
    if (currentSelectedMemoryStores.length > 0) {
      body.resources = currentSelectedMemoryStores.map((id) => ({
        memory_store_id: apiResourceId(id),
        access: 'read_write',
      }))
    }
    const validRepos = selectedRepos.filter((r) => r.url.trim())
    if (validRepos.length > 0) {
      body.repo_resources = validRepos.map((r) => ({
        type: 'github_repository',
        url: r.url.trim(),
        ...(r.branch.trim() ? { branch: r.branch.trim() } : {}),
        ...(r.mount_path.trim() ? { mount_path: r.mount_path.trim() } : {}),
        ...(r.authorization_token.trim()
          ? { authorization_token: r.authorization_token.trim() }
          : {}),
      }))
    }
    return body
  }

  const handleCreate = () => {
    if (!currentManagedScopeIsActive()) return
    if (!currentProjectAllowsWrite()) {
      createRunRef.current += 1
      createMutation.reset()
      resetForm()
      onOpenChange(false)
      return
    }
    const requestScope = managedRequestScopeRef.current
    const scope = requestScope.key
    if (!currentManagedScopeIsActive(scope)) return
    const body = buildCreatePayload(scope)
    if (!body) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    createMutation.mutate({
      body,
      runId,
      scope: requestScope,
    })
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && !currentProjectAllowsWrite()) return
    if (nextOpen && !currentManagedScopeIsActive()) return
    onOpenChange(nextOpen)
    if (!nextOpen) {
      createRunRef.current += 1
      createMutation.reset()
      resetForm()
    }
  }

  const toggleVault = (id: string) => {
    setSelectedVaultIds((prev) =>
      prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id],
    )
  }

  const addFile = (file: FileRecord) => {
    setSelectedFiles((prev) => [
      ...prev,
      { file_id: file.id, filename: file.filename, mount_path: `/workspace/${file.filename}` },
    ])
    setFileSearch('')
    setShowFileDropdown(false)
  }

  const removeFile = (fileId: string) => {
    setSelectedFiles((prev) => prev.filter((f) => f.file_id !== fileId))
  }

  const updateMountPath = (fileId: string, mountPath: string) => {
    setSelectedFiles((prev) =>
      prev.map((f) => (f.file_id === fileId ? { ...f, mount_path: mountPath } : f)),
    )
  }

  const addRepo = () => {
    setSelectedRepos((prev) => [
      ...prev,
      {
        key: `repo-${prev.length}-${Date.now()}`,
        url: '',
        branch: '',
        mount_path: '',
        authorization_token: '',
      },
    ])
  }

  const removeRepo = (key: string) => {
    setSelectedRepos((prev) => prev.filter((r) => r.key !== key))
  }

  const updateRepo = (key: string, patch: Partial<SelectedRepo>) => {
    setSelectedRepos((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  }

  const selectedVaultNames = activeVaults
    .filter((v) => effectiveSelectedVaultIds.includes(v.id))
    .map((v) => v.name)

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">
            {t('managed.sessions.create.title')}
          </DialogTitle>
          <DialogDescription>{t('managed.sessions.create.subtitle')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <FormSectionCard
            title={t('managed.sessions.create.basicSettings', '基础配置')}
            description={t('managed.sessions.create.basicSettingsDesc', '选择要运行的智能体，并可设置本次会话标题。')}
          >
          {/* Title */}
          <div>
            <FormFieldLabel optional={t('managed.sessions.create.optional')} className="mb-1.5">
              {t('managed.sessions.create.sessionTitle')}
            </FormFieldLabel>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('managed.sessions.create.titlePlaceholder')}
            />
          </div>

          {/* Agent */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <FormFieldLabel required>
                {t('managed.sessions.create.agent')}
              </FormFieldLabel>
              <button
                onClick={() => router.push('/managed/agents')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageAgents')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <Select value={effectiveAgentId || undefined} onValueChange={setAgentId}>
              <SelectTrigger className={sessionSelectTriggerClassName}>
                <SelectValue placeholder={t('managed.sessions.create.selectAgent')} />
              </SelectTrigger>
              <SelectContent>
                {/* Sticky search box — typing narrows by agent name or engine
                    label. ``onKeyDown stopPropagation`` keeps Radix from
                    swallowing letters as its "type to focus" shortcut. */}
                <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text"
                      value={agentSearch}
                      onChange={(e) => setAgentSearch(e.target.value)}
                      onKeyDown={(e) => e.stopPropagation()}
                      placeholder={t('managed.sessions.create.searchAgent')}
                      className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    {agentSearch && (
                      <button
                        type="button"
                        onClick={() => setAgentSearch('')}
                        onMouseDown={(e) => e.preventDefault()}
                        aria-label={t('managed.sessions.create.clearSearch')}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
                {agentGroups.length === 0 ? (
                  <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                    {t('managed.sessions.create.noAgentMatch')}
                  </div>
                ) : (
                  agentGroups.map(([engineLabel, groupAgents], gIdx) => {
                    // engine-specific accent color, mirrors the org switcher
                    // tree-grouped look. Order: claude → codex → native → other.
                    const palette = [
                      'bg-purple-500',
                      'bg-blue-500',
                      'bg-emerald-500',
                      'bg-slate-500',
                    ]
                    const dot = palette[gIdx % palette.length]
                    return (
                      <SelectGroup key={engineLabel}>
                        <SelectLabel className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                          <span
                            className={`inline-flex h-4 w-4 items-center justify-center rounded text-[8px] font-bold text-white ${dot} shrink-0`}
                          >
                            {engineLabel.charAt(0).toUpperCase()}
                          </span>
                          {engineLabel}
                          <span className="text-[10px] font-normal text-muted-foreground/60">
                            {t('managed.sessions.create.engineGroupBadge')}
                          </span>
                        </SelectLabel>
                        {groupAgents.map((a, aIdx) => {
                          const isLast = aIdx === groupAgents.length - 1
                          return (
                            <SelectItem key={a.id} value={a.id}>
                              <span className="flex items-center gap-1.5">
                                <span className="w-3 shrink-0 text-[11px] text-muted-foreground/40">
                                  {isLast ? '└' : '├'}
                                </span>
                                <span className="truncate">{a.name}</span>
                              </span>
                            </SelectItem>
                          )
                        })}
                      </SelectGroup>
                    )
                  })
                )}
              </SelectContent>
            </Select>
            {selectedAgent && (
              <div className="mt-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {selectedAgent.name}
                  </span>
                  <span className="shrink-0 rounded bg-background px-1.5 py-0.5 font-mono uppercase">
                    {selectedAgent.engine_kind || t('managed.sessions.create.unknownEngine', 'unknown')}
                  </span>
                </div>
                <div className="mt-1 truncate">
                  {selectedAgentDefaultEnv
                    ? t('managed.sessions.create.selectedAgentEnvironment', {
                        name: selectedAgentDefaultEnv.name,
                      })
                    : t('managed.sessions.create.selectedAgentNoEnvironment', '未配置默认运行环境')}
                </div>
              </div>
            )}
          </div>

          </FormSectionCard>

          <AdvancedSection
            open={showAdvanced}
            onOpenChange={setShowAdvanced}
            title={t('managed.sessions.create.advancedOptions', '高级选项')}
            summary={t('managed.sessions.create.advancedSummary', '运行环境、凭证库、文件资源、Memory、Git')}
          >
          {/* Environment */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <FormFieldLabel
                  optional={t('managed.sessions.create.optional')}
                  tooltip={
                    effectiveEnvId
                      ? t('managed.sessions.create.environmentOverrideHint')
                      : selectedAgentDefaultEnv
                        ? t('managed.sessions.create.environmentUsesAgentDefault', {
                            name: selectedAgentDefaultEnv.name,
                          })
                        : t('managed.sessions.create.environmentFallbackHint')
                  }
                >
                  {t('managed.sessions.create.runtimeEnvironment')}
                </FormFieldLabel>
              </div>
              <button
                onClick={() => router.push('/managed/environments')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageEnvs')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <Select
              value={effectiveEnvId || undefined}
              onValueChange={(value) => {
                if (value === '__create_environment__') {
                  router.push('/managed/environments?create=1')
                  return
                }
                setEnvId(value)
              }}
            >
              <SelectTrigger className={sessionSelectTriggerClassName}>
                <SelectValue placeholder={t('managed.sessions.create.selectEnv')} />
              </SelectTrigger>
              <SelectContent>
                <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text"
                      value={envSearch}
                      onChange={(e) => setEnvSearch(e.target.value)}
                      onKeyDown={(e) => e.stopPropagation()}
                      placeholder={t('managed.sessions.create.searchEnv')}
                      className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    {envSearch && (
                      <button
                        type="button"
                        onClick={() => setEnvSearch('')}
                        onMouseDown={(e) => e.preventDefault()}
                        aria-label={t('managed.sessions.create.clearSearch')}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
                {filteredEnvs.length === 0 ? (
                  <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                    {envSearch
                      ? t('managed.sessions.create.noEnvMatch')
                      : t('managed.sessions.create.noEnvs')}
                  </div>
                ) : (
                  filteredEnvs.map((e) => (
                    <SelectItem key={e.id} value={e.id}>
                      <span className="truncate">{e.name}</span>
                    </SelectItem>
                  ))
                )}
                <SelectItem value="__create_environment__" className="text-primary">
                  <span className="flex items-center gap-1.5">
                    <Plus className="h-3.5 w-3.5" />
                    {t('managed.sessions.create.createEnvironment')}
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Credential Vaults (multi-select) */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <FormFieldLabel optional={t('managed.sessions.create.optional')}>
                {t('managed.sessions.create.vaults')}
              </FormFieldLabel>
              <button
                onClick={() => router.push('/managed/vaults')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageVaults')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <div ref={vaultDropdownRef} className="relative">
              <button
                type="button"
                onClick={() => {
                  setShowVaultDropdown(!showVaultDropdown)
                  setShowFileDropdown(false)
                  setShowMemoryStoreDropdown(false)
                }}
                className={customSelectTriggerClassName}
              >
                <span
                  className={
                    effectiveSelectedVaultIds.length === 0
                      ? 'truncate text-muted-foreground'
                      : 'truncate text-foreground'
                  }
                >
                  {effectiveSelectedVaultIds.length === 0
                    ? t('managed.sessions.create.selectVaults')
                    : selectedVaultNames.join(', ')}
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
              </button>
              {showVaultDropdown && (
                <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-background py-1 shadow-lg">
                  <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        value={vaultSearch}
                        onChange={(e) => setVaultSearch(e.target.value)}
                        onKeyDown={(e) => e.stopPropagation()}
                        placeholder={t('managed.sessions.create.searchVault')}
                        className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      {vaultSearch && (
                        <button
                          type="button"
                          onClick={() => setVaultSearch('')}
                          onMouseDown={(e) => e.preventDefault()}
                          aria-label={t('managed.sessions.create.clearSearch')}
                          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  </div>
                  {filteredVaults.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                      {vaultSearch
                        ? t('managed.sessions.create.noVaultMatch')
                        : t('managed.sessions.create.noVaults')}
                    </div>
                  ) : (
                    filteredVaults.map((v) => (
                      <button
                        key={v.id}
                        type="button"
                        onClick={() => toggleVault(v.id)}
                        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50"
                      >
                        <span
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                            effectiveSelectedVaultIds.includes(v.id)
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border'
                          }`}
                        >
                          {effectiveSelectedVaultIds.includes(v.id) && (
                            <Check className="h-3 w-3" />
                          )}
                        </span>
                        <span>{v.name}</span>
                      </button>
                    ))
                  )}
                  <button
                    type="button"
                    onClick={() => router.push('/managed/vaults?create=1')}
                    className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-sm text-primary hover:bg-muted/50"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {t('managed.sessions.create.createVault')}
                  </button>
                </div>
              )}
            </div>
            {effectiveSelectedVaultIds.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {activeVaults
                  .filter((v) => effectiveSelectedVaultIds.includes(v.id))
                  .map((v) => (
                    <span
                      key={v.id}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs"
                    >
                      {v.name}
                      <button
                        onClick={() => toggleVault(v.id)}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
              </div>
            )}
          </div>

          {/* File Resources */}
          <div>
            <FormFieldLabel optional={t('managed.sessions.create.optional')} className="mb-0.5">
              {t('managed.sessions.create.resources')}
            </FormFieldLabel>
            <p className="mb-2 text-xs text-muted-foreground">
              {t('managed.sessions.create.resourcesDesc')}
            </p>

            {/* Selected files */}
            {effectiveSelectedFiles.length > 0 && (
              <div className="mb-3 space-y-2">
                {effectiveSelectedFiles.map((sf) => (
                  <div
                    key={sf.file_id}
                    className="flex items-center gap-2 rounded-md border border-border p-2"
                  >
                    <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{sf.filename}</div>
                      <Input
                        value={sf.mount_path}
                        onChange={(e) => updateMountPath(sf.file_id, e.target.value)}
                        className="mt-1 h-7 font-mono text-xs"
                        placeholder={t('managed.sessions.create.mountPath')}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(sf.file_id)}
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Add file dropdown */}
            <div ref={fileDropdownRef} className="relative">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowFileDropdown(!showFileDropdown)
                  setShowVaultDropdown(false)
                  setShowMemoryStoreDropdown(false)
                }}
                type="button"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.sessions.create.addResource')}
              </Button>
              {showFileDropdown && (
                <div className="absolute z-50 mt-1 max-h-72 w-80 overflow-y-auto rounded-md border border-border bg-background py-1 shadow-lg">
                  <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        value={fileSearch}
                        onChange={(e) => setFileSearch(e.target.value)}
                        onKeyDown={(e) => e.stopPropagation()}
                        placeholder={t('managed.sessions.create.searchFiles')}
                        className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      {fileSearch && (
                        <button
                          type="button"
                          onClick={() => setFileSearch('')}
                          onMouseDown={(e) => e.preventDefault()}
                          aria-label={t('managed.sessions.create.clearSearch')}
                          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  </div>
                  {filteredAvailableFiles.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                      {fileSearch
                        ? t('managed.sessions.create.noFileMatch')
                        : t('managed.sessions.create.noFiles')}
                    </div>
                  ) : (
                    filteredAvailableFiles.map((f) => (
                      <button
                        key={f.id}
                        type="button"
                        onClick={() => addFile(f)}
                        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50"
                      >
                        <FileIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate">{f.filename}</span>
                        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                          {f.size_bytes < 1024
                            ? `${f.size_bytes} B`
                            : `${(f.size_bytes / 1024).toFixed(1)} KB`}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Memory Stores */}
          <div>
            <FormFieldLabel optional={t('managed.sessions.create.optional')} className="mb-0.5">
              {t('managed.sessions.create.memoryStores')}
            </FormFieldLabel>
            <p className="mb-2 text-xs text-muted-foreground">
              {t('managed.sessions.create.memoryStoresDesc')}
            </p>

            {effectiveSelectedMemoryStores.length > 0 && (
              <div className="mb-3 space-y-2">
                {effectiveSelectedMemoryStores.map((storeId) => {
                  const store = memoryStores.find((memoryStore) => memoryStore.id === storeId)
                  return (
                    <div
                      key={storeId}
                      className="flex items-center gap-2 rounded-md border border-border p-2"
                    >
                      <span className="text-sm">{store?.name || storeId}</span>
                      <span className="flex-1" />
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedMemoryStores((prev) => prev.filter((id) => id !== storeId))
                        }
                        className="shrink-0 text-muted-foreground hover:text-destructive"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}

            <div ref={memoryStoreDropdownRef} className="relative">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowMemoryStoreDropdown(!showMemoryStoreDropdown)
                  setShowVaultDropdown(false)
                  setShowFileDropdown(false)
                }}
                type="button"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.sessions.create.addMemoryStore')}
              </Button>
              {showMemoryStoreDropdown && (
                <div className="absolute z-50 mt-1 max-h-72 w-80 overflow-y-auto rounded-md border border-border bg-background py-1 shadow-lg">
                  <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        value={memoryStoreSearch}
                        onChange={(e) => setMemoryStoreSearch(e.target.value)}
                        onKeyDown={(e) => e.stopPropagation()}
                        placeholder={t('managed.sessions.create.searchMemoryStores')}
                        className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      {memoryStoreSearch && (
                        <button
                          type="button"
                          onClick={() => setMemoryStoreSearch('')}
                          onMouseDown={(e) => e.preventDefault()}
                          aria-label={t('managed.sessions.create.clearSearch')}
                          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  </div>
                  {filteredAvailableMemoryStores.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                      {memoryStoreSearch
                        ? t('managed.sessions.create.noMemoryStoreMatch')
                        : t('managed.sessions.create.noMemoryStores')}
                    </div>
                  ) : (
                    filteredAvailableMemoryStores.map((memoryStore) => (
                      <button
                        key={memoryStore.id}
                        type="button"
                        onClick={() => {
                          setSelectedMemoryStores((prev) => [...prev, memoryStore.id])
                          setMemoryStoreSearch('')
                          setShowMemoryStoreDropdown(false)
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50"
                      >
                        <span className="truncate">{memoryStore.name}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Git Repositories */}
          <div>
            <FormFieldLabel optional={t('managed.sessions.create.optional')} className="mb-0.5">
              {t('managed.sessions.create.repositories')}
            </FormFieldLabel>
            <p className="mb-2 text-xs text-muted-foreground">
              {t('managed.sessions.create.repositoriesDesc')}
            </p>

            {selectedRepos.length > 0 && (
              <div className="mb-3 space-y-2">
                {selectedRepos.map((r) => (
                  <div key={r.key} className="rounded-md border border-border p-2.5">
                    <div className="flex items-start gap-2">
                      <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <Input
                          value={r.url}
                          onChange={(e) => updateRepo(r.key, { url: e.target.value })}
                          className="h-7 font-mono text-xs"
                          placeholder={t('managed.sessions.create.repoUrlPlaceholder')}
                        />
                        <div className="flex gap-1.5">
                          <Input
                            value={r.branch}
                            onChange={(e) => updateRepo(r.key, { branch: e.target.value })}
                            className="h-7 font-mono text-xs"
                            placeholder={t('managed.sessions.create.repoBranch')}
                          />
                          <Input
                            value={r.mount_path}
                            onChange={(e) => updateRepo(r.key, { mount_path: e.target.value })}
                            className="h-7 font-mono text-xs"
                            placeholder={t('managed.sessions.create.mountPath')}
                          />
                        </div>
                        <Input
                          type="password"
                          autoComplete="new-password"
                          value={r.authorization_token}
                          onChange={(e) =>
                            updateRepo(r.key, { authorization_token: e.target.value })
                          }
                          className="h-7 font-mono text-xs"
                          placeholder={t('managed.sessions.create.repoTokenPlaceholder')}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => removeRepo(r.key)}
                        className="shrink-0 text-muted-foreground hover:text-destructive"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
                <p className="text-xs text-muted-foreground">
                  {t('managed.sessions.create.repoTokenHint')}
                </p>
              </div>
            )}

            <Button variant="outline" size="sm" onClick={addRepo} type="button">
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {t('managed.sessions.create.addRepository')}
            </Button>
          </div>
          </AdvancedSection>
        </div>

        <FormActionBar>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleCreate} disabled={!effectiveAgentId || createMutation.isPending}>
            {createMutation.isPending
              ? t('managed.sessions.create.creating')
              : t('managed.sessions.create.submit')}
          </Button>
        </FormActionBar>
      </DialogContent>
    </Dialog>
  )
}
