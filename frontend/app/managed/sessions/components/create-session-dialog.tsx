'use client'

import { useState, useMemo } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Plus, ExternalLink, X, Check, FileIcon } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { managedGet, managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { FieldHelp } from '@/components/managed/shared'
import type { Agent, Environment, Vault, FileRecord, PaginatedResponse } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'

interface SelectedFile {
  file_id: string
  filename: string
  mount_path: string
}

interface CreateSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (sessionId: string) => void
}

export function CreateSessionDialog({ open, onOpenChange, onCreated }: CreateSessionDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const [title, setTitle] = useState('')
  const [agentId, setAgentId] = useState('')
  const [envId, setEnvId] = useState('')
  const [selectedVaultIds, setSelectedVaultIds] = useState<string[]>([])
  const [showVaultDropdown, setShowVaultDropdown] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([])
  const [showFileDropdown, setShowFileDropdown] = useState(false)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents-for-session'],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Agent>>('/agents')
      return res.data || []
    },
    enabled: open,
  })

  const { data: environments = [] } = useQuery({
    queryKey: ['envs-for-session'],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Environment>>('/environments')
      return res.data || []
    },
    enabled: open,
  })

  const { data: vaultsRes } = useQuery({
    queryKey: ['vaults-for-session'],
    queryFn: () => managedGet<{ data: Vault[] }>('/vaults'),
    enabled: open,
  })
  const vaults = vaultsRes?.data || []

  const { data: filesResp } = useQuery({
    queryKey: ['files-for-session'],
    queryFn: () => managedGet<{ data: FileRecord[] }>('/files?limit=100'),
    enabled: open,
  })
  const files = useMemo(() => {
    if (!filesResp) return []
    return filesResp.data || []
  }, [filesResp])

  const activeAgents = useMemo(() => agents.filter((a) => !a.archived_at), [agents])
  const activeEnvs = useMemo(() => environments.filter((e) => !e.archived_at), [environments])
  const activeVaults = useMemo(() => vaults.filter((v) => !v.archived_at), [vaults])
  const selectedAgent = useMemo(() => activeAgents.find((agent) => agent.id === agentId), [activeAgents, agentId])
  const selectedAgentDefaultEnv = useMemo(() => {
    const ref = selectedAgent?.environment_ref
    if (!ref) return null
    return activeEnvs.find((env) => env.id === ref || stripIdPrefix(env.id) === stripIdPrefix(ref)) || null
  }, [activeEnvs, selectedAgent])

  const availableFiles = useMemo(
    () => files.filter((f) => !selectedFiles.some((sf) => sf.file_id === f.id)),
    [files, selectedFiles],
  )

  const createMutation = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        agent: stripIdPrefix(agentId),
      }
      if (title.trim()) body.title = title.trim()
      if (envId) body.environment_id = stripIdPrefix(envId)
      if (selectedVaultIds.length > 0) {
        body.vault_ids = selectedVaultIds.map(stripIdPrefix)
      }
      if (selectedFiles.length > 0) {
        body.file_resources = selectedFiles.map((f) => ({
          type: 'file',
          file_id: f.file_id,
          mount_path: f.mount_path,
        }))
      }
      return managedPost<{ id: string }>('/sessions', body)
    },
    onSuccess: (res) => {
      onOpenChange(false)
      resetForm()
      if (onCreated) {
        onCreated(res.id)
      } else {
        router.push(`/managed/sessions/${res.id}`)
      }
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const resetForm = () => {
    setTitle('')
    setAgentId('')
    setEnvId('')
    setSelectedVaultIds([])
    setSelectedFiles([])
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

  const selectedVaultNames = activeVaults
    .filter((v) => selectedVaultIds.includes(v.id))
    .map((v) => v.name)

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) resetForm()
      }}
    >
      <DialogContent className="sm:max-w-[560px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">{t('managed.sessions.create.title')}</DialogTitle>
          <DialogDescription>{t('managed.sessions.create.subtitle')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-4">
          {/* Title */}
          <div>
            <label className="mb-1.5 block text-sm font-medium">{t('managed.sessions.create.sessionTitle')}</label>
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
            <Select value={agentId || undefined} onValueChange={setAgentId}>
              <SelectTrigger>
                <SelectValue placeholder={t('managed.sessions.create.selectAgent')} />
              </SelectTrigger>
              <SelectContent>
                {activeAgents.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Environment */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <label className="text-sm font-medium">{t('managed.sessions.create.environment')}</label>
                <FieldHelp
                  text={envId
                    ? t('managed.sessions.create.environmentOverrideHint')
                    : selectedAgentDefaultEnv
                      ? t('managed.sessions.create.environmentUsesAgentDefault', { name: selectedAgentDefaultEnv.name })
                      : t('managed.sessions.create.environmentFallbackHint')}
                />
              </div>
              <button
                onClick={() => router.push('/managed/environments')}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('managed.sessions.create.manageEnvs')} <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <Select value={envId || undefined} onValueChange={setEnvId}>
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
                <span className={selectedVaultIds.length === 0 ? 'text-muted-foreground' : 'text-foreground'}>
                  {selectedVaultIds.length === 0
                    ? t('managed.sessions.create.selectVaults')
                    : selectedVaultNames.join(', ')}
                </span>
                <svg className="h-4 w-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
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
                            selectedVaultIds.includes(v.id)
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border'
                          }`}
                        >
                          {selectedVaultIds.includes(v.id) && <Check className="h-3 w-3" />}
                        </span>
                        <span>{v.name}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
            {selectedVaultIds.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {activeVaults
                  .filter((v) => selectedVaultIds.includes(v.id))
                  .map((v) => (
                    <span
                      key={v.id}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs"
                    >
                      {v.name}
                      <button onClick={() => toggleVault(v.id)} className="text-muted-foreground hover:text-foreground">
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
              </div>
            )}
          </div>

          {/* File Resources */}
          <div>
            <label className="mb-0.5 block text-sm font-medium">{t('managed.sessions.create.resources')}</label>
            <p className="mb-2 text-xs text-muted-foreground">{t('managed.sessions.create.resourcesDesc')}</p>

            {/* Selected files */}
            {selectedFiles.length > 0 && (
              <div className="mb-3 space-y-2">
                {selectedFiles.map((sf) => (
                  <div key={sf.file_id} className="flex items-center gap-2 rounded-md border border-border p-2">
                    <FileIcon className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{sf.filename}</div>
                      <Input
                        value={sf.mount_path}
                        onChange={(e) => updateMountPath(sf.file_id, e.target.value)}
                        className="mt-1 h-7 text-xs font-mono"
                        placeholder={t('managed.sessions.create.mountPath')}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(sf.file_id)}
                      className="text-muted-foreground hover:text-destructive shrink-0"
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
                <div className="absolute z-50 mt-1 w-64 rounded-md border border-border bg-background py-1 shadow-lg max-h-48 overflow-y-auto">
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
                        <FileIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="truncate">{f.filename}</span>
                        <span className="text-xs text-muted-foreground ml-auto shrink-0">
                          {f.size_bytes < 1024 ? `${f.size_bytes} B` : `${(f.size_bytes / 1024).toFixed(1)} KB`}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!agentId || createMutation.isPending}
          >
            {createMutation.isPending ? t('managed.sessions.create.creating') : t('managed.sessions.create.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
