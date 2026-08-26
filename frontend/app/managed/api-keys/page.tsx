'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  DataTable,
  FilterBar,
  MonoId,
  PageHeader,
  RelativeTime,
  ResourceErrorState,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import {
  parseApiKeyCreateResponse,
  parseApiKeyResponse,
} from '@/lib/managed/api-key-response-parsers'
import {
  apiKeyStatusLabelKey,
  buildApiKeyCreatePayload,
  canRevokeApiKey,
} from '@/lib/managed/api-key-lifecycle'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { projectRoleLabel, projectRoleOptions } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'
import { parseApiKeyId, type ApiKeyId } from '@/types/entity-id'
import type { ApiKey } from '@/types/managed'

interface ProjectSummary {
  id: string
  org_id: string
  capability?: string
  archived_at?: string | null
}

interface RevokeKeyVariables {
  id: ApiKeyId
  scope: string
  runId: number
}

interface CreateKeyVariables {
  name: string
  role: string
  expiresAt: string
  scope: string
  runId: number
}

export default function ApiKeysPage({ projectId }: { projectId?: string } = {}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const currentProject = useProjectStore((state) => state.currentProject)
  const targetProjectId = projectId || currentProjectId || ''
  const targetProjectQuery = useQuery({
    queryKey: ['project', targetProjectId],
    queryFn: () => managedGet<ProjectSummary>(`auth/projects/${targetProjectId}`),
    enabled: Boolean(projectId && targetProjectId),
  })
  const targetProject = projectId ? targetProjectQuery.data : currentProject
  const projectReadOnly =
    !targetProject || Boolean(targetProject.archived_at) || targetProject.capability !== 'admin'
  const apiKeysPath = projectId ? `/auth/projects/${targetProjectId}/api-keys` : '/auth/api-keys'
  const managedScope = `${currentOrgId ?? ''}:${targetProjectId}`
  const managedScopeRef = useRef(managedScope)
  const createKeyRunRef = useRef(0)
  const revokeKeyRunRef = useRef(0)
  const copiedResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [keyRole, setKeyRole] = useState('viewer')
  const [keyExpiresAt, setKeyExpiresAt] = useState('')
  const [newRawKey, setNewRawKey] = useState<string | null>(null)
  const [newRawKeyName, setNewRawKeyName] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const {
    data: keys,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset: resetApiKeyPagination,
  } = usePaginatedList<ApiKey>({
    queryKey: 'api-keys',
    path: apiKeysPath,
    enabled: Boolean(targetProjectId),
    parseItem: parseApiKeyResponse,
    parseCursor: parseApiKeyId,
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
    setKeyExpiresAt('')
    setNewRawKey(null)
    setNewRawKeyName(null)
    setCopied(false)
    setDeleteTarget(null)
    resetApiKeyPagination()
  }, [managedScope, resetApiKeyPagination])

  useEffect(() => {
    if (!projectReadOnly) return
    createKeyRunRef.current += 1
    revokeKeyRunRef.current += 1
    setShowCreate(false)
    setKeyName('')
    setKeyRole('viewer')
    setKeyExpiresAt('')
    setNewRawKey(null)
    setNewRawKeyName(null)
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
      matchesSearch(searchQuery, [key.id, key.name, key.key_prefix, key.role, key.status]),
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
      key: 'status',
      header: t('manage.apiKeys.statusLabel'),
      render: (key) => (
        <Badge variant={key.status === 'revoked' ? 'destructive' : 'outline'}>
          {t(apiKeyStatusLabelKey(key.status))}
        </Badge>
      ),
    },
    {
      key: 'expires',
      header: t('manage.apiKeys.expiresAt'),
      render: (key) =>
        key.expires_at ? (
          <RelativeTime date={key.expires_at} />
        ) : (
          <span className="text-muted-foreground">{t('manage.apiKeys.neverExpires')}</span>
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
    return `${currentOrgId ?? ''}:${projectId || currentProjectId || ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope

  const currentManagedScopeAllowsWrite = (scope = managedScopeRef.current) =>
    currentManagedScopeIsActive(scope) && !projectReadOnly

  const createKey = useMutation({
    mutationFn: (data: CreateKeyVariables) => {
      if (!currentManagedScopeAllowsWrite(data.scope) || data.runId !== createKeyRunRef.current) {
        throw new Error('Stale api key create ignored')
      }
      return managedPost<unknown>(
        apiKeysPath,
        buildApiKeyCreatePayload(data.name, data.role, data.expiresAt),
      )
        .then(parseApiKeyCreateResponse)
        .then((res) => ({ res, runId: data.runId, scope: data.scope, name: data.name }))
    },
    onSuccess: ({ res, runId, scope, name }) => {
      if (!currentManagedScopeAllowsWrite(scope)) return
      if (runId !== createKeyRunRef.current) return
      resetApiKeyPagination()
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setNewRawKey(res.raw_key)
      setNewRawKeyName(name)
      setShowCreate(false)
      setKeyName('')
      setKeyExpiresAt('')
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
    if (projectReadOnly) return
    createKeyRunRef.current += 1
    setShowCreate(true)
  }

  const handleCreateOpenChange = (open: boolean) => {
    if (open && projectReadOnly) return
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
    createKey.mutate({
      name,
      role: keyRole,
      expiresAt: keyExpiresAt,
      runId,
      scope: managedScopeRef.current,
    })
  }

  const revokeKey = useMutation({
    mutationFn: ({ id, runId, scope }: RevokeKeyVariables) => {
      if (!currentManagedScopeAllowsWrite(scope) || runId !== revokeKeyRunRef.current) {
        throw new Error('Stale api key revoke ignored')
      }
      return managedDelete(
        projectId ? `/auth/projects/${targetProjectId}/api-keys/${id}` : `/auth/api-keys/${id}`,
      )
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!currentManagedScopeAllowsWrite(scope) || runId !== revokeKeyRunRef.current) return
      resetApiKeyPagination()
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
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
        .getQueriesData<{ data: ApiKey[] }>({ queryKey: ['api-keys'] })
        .flatMap(([, page]) => page?.data ?? [])
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
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['api-keys'] })}
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
        <Alert variant="success" className="mb-4">
          <AlertDescription>
            <p className="mb-1 text-sm font-medium">
              {t('manage.apiKeys.createdToken', { name: newRawKeyName || '' })}
            </p>
            <p className="mb-2 text-sm">{t('manage.apiKeys.newKeyWarning')}</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded border bg-background px-3 py-2 font-mono text-xs">
                {newRawKey}
              </code>
              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => handleCopy(newRawKey)}
                aria-label={copied ? t('common.copied') : t('common.copy')}
                title={copied ? t('common.copied') : t('common.copy')}
              >
                {copied ? <Check /> : <Copy />}
              </Button>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 text-xs"
              onClick={() => {
                setNewRawKey(null)
                setNewRawKeyName(null)
              }}
            >
              {t('manage.apiKeys.savedConfirmation')}
            </Button>
          </AlertDescription>
        </Alert>
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
              <label className="space-y-1 text-sm" htmlFor="api-key-expires-at">
                <span className="text-muted-foreground">
                  {t('manage.apiKeys.expiresAtOptional')}
                </span>
                <Input
                  id="api-key-expires-at"
                  type="datetime-local"
                  value={keyExpiresAt}
                  onChange={(event) => setKeyExpiresAt(event.target.value)}
                />
              </label>
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
        fetching={isFetching}
        emptyMessage={t('manage.apiKeys.empty')}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
        actionMenu={
          !projectReadOnly
            ? (key) =>
                canRevokeApiKey(key.status)
                  ? [
                      {
                        label: t('manage.apiKeys.revoke'),
                        icon: <Trash2 className="h-3.5 w-3.5" />,
                        destructive: true,
                        onClick: () => openRevokeDialog(key),
                      },
                    ]
                  : []
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
            <DialogDescription>
              {t('manage.apiKeys.revokeDescNamed', { name: deleteTarget?.name || '' })}
            </DialogDescription>
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
