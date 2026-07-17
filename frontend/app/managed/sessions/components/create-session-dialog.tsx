'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, ExternalLink, X, Check, FileIcon, GitBranch, Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { FieldHelp } from '@/components/managed/shared'
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

export function CreateSessionDialog({ open, onOpenChange, onCreated }: CreateSessionDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const createRunRef = useRef(0)

  const [title, setTitle] = useState('')
  const [agentId, setAgentId] = useState('')
  const [agentSearch, setAgentSearch] = useState('')
  const [envId, setEnvId] = useState('')
  const [selectedVaultIds, setSelectedVaultIds] = useState<string[]>([])
  const [showVaultDropdown, setShowVaultDropdown] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([])
  const [showFileDropdown, setShowFileDropdown] = useState(false)
  const [selectedRepos, setSelectedRepos] = useState<SelectedRepo[]>([])
  const [selectedMemoryStores, setSelectedMemoryStores] = useState<string[]>([])
  const [showMemoryStoreDropdown, setShowMemoryStoreDropdown] = useState(false)

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

  const resetForm = () => {
    setTitle('')
    setAgentId('')
    setAgentSearch('')
    setEnvId('')
    setSelectedVaultIds([])
    setShowVaultDropdown(false)
    setSelectedFiles([])
    setShowFileDropdown(false)
    setSelectedRepos([])
    setSelectedMemoryStores([])
    setShowMemoryStoreDropdown(false)
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
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">
            {t('managed.sessions.create.title')}
          </DialogTitle>
          <DialogDescription>{t('managed.sessions.create.subtitle')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-4">
          {/* Title */}
          <div>
            <label className="mb-1.5 block text-sm font-medium">
              {t('managed.sessions.create.sessionTitle')}
            </label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('managed.sessions.create.titlePlaceholder')}
            />
          </div>

          {/* Agent */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-sm font-medium">{t('managed.sessions.create.agent')}</label>
              <button
                onClick={() => router.push('/managed/agents')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageAgents')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <Select value={effectiveAgentId || undefined} onValueChange={setAgentId}>
              <SelectTrigger>
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
          </div>

          {/* Environment */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <label className="text-sm font-medium">
                  {t('managed.sessions.create.environment')}
                </label>
                <FieldHelp
                  text={
                    effectiveEnvId
                      ? t('managed.sessions.create.environmentOverrideHint')
                      : selectedAgentDefaultEnv
                        ? t('managed.sessions.create.environmentUsesAgentDefault', {
                            name: selectedAgentDefaultEnv.name,
                          })
                        : t('managed.sessions.create.environmentFallbackHint')
                  }
                />
              </div>
              <button
                onClick={() => router.push('/managed/environments')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageEnvs')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <Select value={effectiveEnvId || undefined} onValueChange={setEnvId}>
              <SelectTrigger>
                <SelectValue placeholder={t('managed.sessions.create.selectEnv')} />
              </SelectTrigger>
              <SelectContent>
                {activeEnvs.map((e) => (
                  <SelectItem key={e.id} value={e.id}>
                    {e.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Credential Vaults (multi-select) */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-sm font-medium">{t('managed.sessions.create.vaults')}</label>
              <button
                onClick={() => router.push('/managed/vaults')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageVaults')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowVaultDropdown(!showVaultDropdown)}
                className="flex h-9 w-full items-center justify-between rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <span
                  className={
                    effectiveSelectedVaultIds.length === 0
                      ? 'text-muted-foreground'
                      : 'text-foreground'
                  }
                >
                  {effectiveSelectedVaultIds.length === 0
                    ? t('managed.sessions.create.selectVaults')
                    : selectedVaultNames.join(', ')}
                </span>
                <svg
                  className="h-4 w-4 opacity-50"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </button>
              {showVaultDropdown && (
                <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-background py-1 shadow-lg">
                  {activeVaults.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-muted-foreground">
                      {t('managed.sessions.create.noVaults')}
                    </div>
                  ) : (
                    activeVaults.map((v) => (
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
            <label className="mb-0.5 block text-sm font-medium">
              {t('managed.sessions.create.resources')}
            </label>
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
            <div className="relative">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowFileDropdown(!showFileDropdown)}
                type="button"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.sessions.create.addResource')}
              </Button>
              {showFileDropdown && (
                <div className="absolute z-50 mt-1 max-h-48 w-64 overflow-y-auto rounded-md border border-border bg-background py-1 shadow-lg">
                  {availableFiles.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-muted-foreground">
                      {t('managed.sessions.create.noFiles')}
                    </div>
                  ) : (
                    availableFiles.map((f) => (
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
            <label className="mb-0.5 block text-sm font-medium">
              {t('managed.sessions.create.memoryStores')}
            </label>
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

            <div className="relative">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowMemoryStoreDropdown(!showMemoryStoreDropdown)}
                type="button"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.sessions.create.addMemoryStore')}
              </Button>
              {showMemoryStoreDropdown && (
                <div className="absolute z-50 mt-1 max-h-48 w-64 overflow-y-auto rounded-md border border-border bg-background py-1 shadow-lg">
                  {availableMemoryStores.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-muted-foreground">
                      {t('managed.sessions.create.noMemoryStores')}
                    </div>
                  ) : (
                    availableMemoryStores.map((memoryStore) => (
                      <button
                        key={memoryStore.id}
                        type="button"
                        onClick={() => {
                          setSelectedMemoryStores((prev) => [...prev, memoryStore.id])
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
            <label className="mb-0.5 block text-sm font-medium">
              {t('managed.sessions.create.repositories')}
            </label>
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
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleCreate} disabled={!effectiveAgentId || createMutation.isPending}>
            {createMutation.isPending
              ? t('managed.sessions.create.creating')
              : t('managed.sessions.create.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
