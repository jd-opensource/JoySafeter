'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Plus, Trash2, Copy, Check } from 'lucide-react'
import {
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  type Column,
  type FilterDef,
  PageHeader,
  ResourceErrorState,
} from '@/components/managed/shared'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { projectRoleLabel, projectRoleOptions } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface ApiKey {
  id: string
  project_id: string
  name: string
  key_prefix: string
  role: string
  created_at?: string
  last_used_at?: string
}

interface RevokeKeyVariables {
  id: string
  scope: string
  runId: number
}

interface CreateKeyVariables {
  name: string
  role: string
  scope: string
  runId: number
}

export default function ApiKeysPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const managedScopeRef = useRef(managedScope)
  const createKeyRunRef = useRef(0)
  const revokeKeyRunRef = useRef(0)
  const copiedResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [keyRole, setKeyRole] = useState('viewer')
  const [newRawKey, setNewRawKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')

  const {
    data: keys = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['api-keys', currentOrgId, currentProjectId],
    queryFn: async () => managedGet<ApiKey[]>('/auth/api-keys'),
  })

  useEffect(
    () => () => {
      createKeyRunRef.current += 1
      revokeKeyRunRef.current += 1
      if (copiedResetTimerRef.current) {
        clearTimeout(copiedResetTimerRef.current)
      }
    },
    [],
  )

  useEffect(() => {
    managedScopeRef.current = managedScope
    createKeyRunRef.current += 1
    revokeKeyRunRef.current += 1
    if (copiedResetTimerRef.current) {
      clearTimeout(copiedResetTimerRef.current)
      copiedResetTimerRef.current = null
    }
    setShowCreate(false)
    setKeyName('')
    setKeyRole('viewer')
    setNewRawKey(null)
    setCopied(false)
    setDeleteTarget(null)
  }, [managedScope])

  useEffect(() => {
    if (!projectReadOnly) return
    createKeyRunRef.current += 1
    revokeKeyRunRef.current += 1
    setShowCreate(false)
    setKeyName('')
    setKeyRole('viewer')
    setNewRawKey(null)
    setCopied(false)
    setDeleteTarget(null)
  }, [projectReadOnly])

  useEffect(() => {
    setDeleteTarget((target) => {
      if (!target) return null
      const current = keys.find((key) => key.id === target.id) ?? null
      if (!current) revokeKeyRunRef.current += 1
      return current
    })
  }, [keys])

  const filteredKeys = keys.filter(
    (key) =>
      filterByCreatedTime(key.created_at || '', createdFilter) &&
      matchesSearch(searchQuery, [key.id, key.name, key.key_prefix, key.role]),
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]
  const columns: Column<ApiKey>[] = [
    {
      key: 'name',
      header: t('manage.apiKeys.keyName'),
      render: (key) => <span className="font-medium text-foreground">{key.name}</span>,
    },
    {
      key: 'prefix',
      header: t('manage.apiKeys.prefix'),
      render: (key) => <MonoId id={`${key.key_prefix}...`} truncate={false} />,
    },
    {
      key: 'role',
      header: t('manage.apiKeys.role'),
      render: (key) => (
        <span className="text-muted-foreground">{projectRoleLabel(t, key.role)}</span>
      ),
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (key) =>
        key.created_at ? (
          <RelativeTime date={key.created_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
    {
      key: 'last_used',
      header: t('manage.apiKeys.lastUsed'),
      render: (key) =>
        key.last_used_at ? (
          <RelativeTime date={key.last_used_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  const getCurrentManagedScope = () => {
    const { currentOrgId, currentProjectId } = useProjectStore.getState()
    return `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  }

  const apiKeysQueryKey = (scope = managedScopeRef.current) => {
    const [orgId = '', projectId = ''] = scope.split(':', 2)
    return ['api-keys', orgId || null, projectId || null] as const
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope

  const currentManagedScopeAllowsWrite = (scope = managedScopeRef.current) =>
    currentManagedScopeIsActive(scope) && currentProjectAllowsWrite()

  const createKey = useMutation({
    mutationFn: (data: CreateKeyVariables) => {
      if (!currentManagedScopeAllowsWrite(data.scope) || data.runId !== createKeyRunRef.current) {
        throw new Error('Stale api key create ignored')
      }
      return managedPost<{ raw_key: string }>('/auth/api-keys', {
        name: data.name,
        role: data.role,
      }).then((res) => ({ res, runId: data.runId, scope: data.scope }))
    },
    onSuccess: ({ res, runId, scope }) => {
      if (!currentManagedScopeAllowsWrite(scope)) return
      if (runId !== createKeyRunRef.current) return
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey(scope) })
      setNewRawKey(res.raw_key)
      setShowCreate(false)
      setKeyName('')
    },
    onError: (error, variables) => {
      if (
        !currentManagedScopeAllowsWrite(variables.scope) ||
        variables.runId !== createKeyRunRef.current
      ) {
        return
      }
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const openCreateDialog = () => {
    if (!currentProjectAllowsWrite()) return
    createKeyRunRef.current += 1
    setShowCreate(true)
  }

  const handleCreateOpenChange = (open: boolean) => {
    if (open && !currentProjectAllowsWrite()) return
    if (!open) {
      createKeyRunRef.current += 1
    }
    setShowCreate(open)
  }

  const submitCreateKey = () => {
    const name = keyName.trim()
    if (!name) return
    if (!currentManagedScopeAllowsWrite()) {
      handleCreateOpenChange(false)
      return
    }
    const runId = createKeyRunRef.current + 1
    createKeyRunRef.current = runId
    createKey.mutate({ name, role: keyRole, runId, scope: managedScopeRef.current })
  }

  const revokeKey = useMutation({
    mutationFn: ({ id, runId, scope }: RevokeKeyVariables) => {
      if (!currentManagedScopeAllowsWrite(scope) || runId !== revokeKeyRunRef.current) {
        throw new Error('Stale api key revoke ignored')
      }
      return managedDelete(`/auth/api-keys/${id}`)
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!currentManagedScopeAllowsWrite(scope) || runId !== revokeKeyRunRef.current) return
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey(scope) })
    },
    onError: (error, { runId, scope }) => {
      if (!currentManagedScopeAllowsWrite(scope) || runId !== revokeKeyRunRef.current) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const currentApiKey = (key: ApiKey | null) => {
    if (!key) return null
    if (!currentManagedScopeAllowsWrite()) return null
    return (
      queryClient
        .getQueryData<ApiKey[]>(['api-keys', currentOrgId, currentProjectId])
        ?.find((candidate) => candidate.id === key.id) ?? null
    )
  }

  const openRevokeDialog = (key: ApiKey) => {
    if (!currentManagedScopeAllowsWrite()) return
    if (!currentApiKey(key)) return

    revokeKeyRunRef.current += 1
    setDeleteTarget(key)
  }

  const closeRevokeDialog = () => {
    revokeKeyRunRef.current += 1
    setDeleteTarget(null)
  }

  const submitRevokeKey = () => {
    if (!currentManagedScopeAllowsWrite()) {
      closeRevokeDialog()
      return
    }
    const target = currentApiKey(deleteTarget)
    if (!target) {
      closeRevokeDialog()
      return
    }
    const runId = revokeKeyRunRef.current + 1
    revokeKeyRunRef.current = runId
    revokeKey.mutate({ id: target.id, scope: managedScopeRef.current, runId })
    setDeleteTarget(null)
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="apiKey"
        onRetry={() => queryClient.invalidateQueries({ queryKey: apiKeysQueryKey() })}
      />
    )
  }

  const showCopiedFeedback = () => {
    if (copiedResetTimerRef.current) {
      clearTimeout(copiedResetTimerRef.current)
    }
    setCopied(true)
    copiedResetTimerRef.current = setTimeout(() => {
      setCopied(false)
      copiedResetTimerRef.current = null
    }, 2000)
  }

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text)
    showCopiedFeedback()
  }

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.apiKeys.title')}
        subtitle={t('manage.apiKeys.subtitle')}
        action={
          !projectReadOnly ? (
            <Button size="sm" onClick={openCreateDialog}>
              <Plus className="mr-1 h-4 w-4" />
              {t('manage.apiKeys.create')}
            </Button>
          ) : null
        }
      />

      {newRawKey && (
        <div className="mb-4 rounded-lg border border-green-500/50 bg-green-50 p-4 dark:bg-green-950/20">
          <p className="mb-2 text-sm font-medium">{t('manage.apiKeys.newKeyWarning')}</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded border bg-background px-3 py-2 font-mono text-xs">
              {newRawKey}
            </code>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={() => handleCopy(newRawKey)}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-green-500" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 text-xs"
            onClick={() => setNewRawKey(null)}
          >
            {t('manage.apiKeys.dismiss')}
          </Button>
        </div>
      )}

      <FilterBar
        searchPlaceholder={t('managed.search.apiKeys')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />

      {!projectReadOnly && showCreate && (
        <Dialog open={!projectReadOnly && showCreate} onOpenChange={handleCreateOpenChange}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t('manage.apiKeys.create')}</DialogTitle>
              <DialogDescription>{t('manage.apiKeys.subtitle')}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Input
                placeholder={t('manage.apiKeys.namePlaceholder')}
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
              />
              <Select value={keyRole} onValueChange={setKeyRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {projectRoleOptions(t).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => handleCreateOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button onClick={submitCreateKey} disabled={!keyName.trim()}>
                {t('manage.apiKeys.create')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <DataTable
        columns={columns}
        data={filteredKeys}
        loading={isLoading}
        emptyMessage={t('manage.apiKeys.empty')}
        actionMenu={
          !projectReadOnly
            ? (key) => [
                {
                  label: t('manage.apiKeys.revoke'),
                  icon: <Trash2 className="h-3.5 w-3.5" />,
                  destructive: true,
                  onClick: () => openRevokeDialog(key),
                },
              ]
            : undefined
        }
      />

      <Dialog
        open={!projectReadOnly && !!deleteTarget}
        onOpenChange={(open) => !open && closeRevokeDialog()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.apiKeys.revokeTitle')}</DialogTitle>
            <DialogDescription>{t('manage.apiKeys.revokeDesc')}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {deleteTarget?.name} ({deleteTarget?.key_prefix}...)
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={closeRevokeDialog}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={submitRevokeKey}>
              {t('manage.apiKeys.revoke')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
