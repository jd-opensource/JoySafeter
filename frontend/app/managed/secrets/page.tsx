'use client'

import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { Check, CheckCircle2, Loader2, Plus, Star, Trash2, Wifi, XCircle } from 'lucide-react'
import { managedPost, managedDelete } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { parseApiError, toastOperationError } from '@/lib/managed/errors'
import {
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { Secret } from '@/types/managed'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import {
  getDefaultProtocol,
  getDefaultSecretPairs,
  getSecretProviderLabel,
  isCustomSecretProvider,
  isModelKey,
  isSecretValueMaskedKey,
  SECRET_PROTOCOL_OPTIONS,
  SECRET_PROVIDER_GROUPS,
} from '@/lib/managed/secret-keys'
import { SecretKeySelect, SecretModelInput } from '@/components/managed/shared'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  MonoId,
  RelativeTime,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface KVPair {
  key: string
  value: string
}

interface SecretTestResult {
  ok: boolean
  provider: string
  protocol: string
  message: string
  endpoint?: string | null
  status?: number | null
  error_detail?: string | null
}

interface ScopedRun {
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export default function SecretListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef(managedScope)
  const createRunRef = useRef(0)
  const testRunRef = useRef(0)
  const deleteRunRef = useRef(0)
  const defaultRunRef = useRef(0)
  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }
  const isCurrentManagedScope = (scope: string) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope
  const nextScopedRun = (runRef: MutableRefObject<number>): ScopedRun => {
    const runId = runRef.current + 1
    runRef.current = runId
    return {
      runId,
      scope: managedScopeRef.current,
      requestScope: managedRequestScopeRef.current,
    }
  }
  const isCurrentScopedRun = (runRef: MutableRefObject<number>, action: ScopedRun) =>
    runRef.current === action.runId &&
    isCurrentManagedScope(action.scope) &&
    currentProjectAllowsWrite()
  const {
    data: secrets,
    isLoading: secretsLoading,
    isFetching: secretsFetching,
    isError: secretsIsError,
    error: secretsError,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
  } = usePaginatedList<Secret>({ queryKey: 'secrets', path: '/secrets' })
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [secretKind, setSecretKind] = useState<'llm' | 'custom'>('llm')
  const [newProvider, setNewProvider] = useState('claude')
  const [newProtocol, setNewProtocol] = useState('anthropic_messages')
  const [pairs, setPairs] = useState<KVPair[]>([{ key: '', value: '' }])
  const [creating, setCreating] = useState(false)
  const [testingSecret, setTestingSecret] = useState(false)
  const [testResult, setTestResult] = useState<SecretTestResult | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    testRunRef.current += 1
    deleteRunRef.current += 1
    defaultRunRef.current += 1
    setShowCreate(false)
    setNewName('')
    setSecretKind('llm')
    setNewProvider('claude')
    setNewProtocol('anthropic_messages')
    setPairs(getDefaultSecretPairs('claude', 'anthropic_messages'))
    setCreating(false)
    setTestingSecret(false)
    setTestResult(null)
    setDeleteTarget(null)
  }, [managedScope.key])

  useEffect(
    () => () => {
      createRunRef.current += 1
      testRunRef.current += 1
      deleteRunRef.current += 1
      defaultRunRef.current += 1
    },
    [],
  )

  const resetCreateDraft = () => {
    setNewName('')
    setSecretKind('llm')
    setNewProvider('claude')
    setNewProtocol('anthropic_messages')
    setPairs(getDefaultSecretPairs('claude', 'anthropic_messages'))
    setCreating(false)
    setTestingSecret(false)
    setTestResult(null)
  }

  const invalidatePendingTest = () => {
    testRunRef.current += 1
    setTestingSecret(false)
    setTestResult(null)
  }

  const updatePair = (index: number, field: 'key' | 'value', val: string) => {
    invalidatePendingTest()
    setPairs((prev) => prev.map((p, i) => (i === index ? { ...p, [field]: val } : p)))
  }

  const removePair = (index: number) => {
    invalidatePendingTest()
    setPairs((prev) => prev.filter((_, i) => i !== index))
  }

  const addPair = () => {
    invalidatePendingTest()
    setPairs((prev) => [...prev, { key: '', value: '' }])
  }

  const updateProvider = (provider: string) => {
    const nextProtocol = getDefaultProtocol(provider)
    invalidatePendingTest()
    setNewProvider(provider)
    setNewProtocol(nextProtocol)
    setPairs(getDefaultSecretPairs(provider, nextProtocol))
  }

  const updateProtocol = (protocol: string) => {
    invalidatePendingTest()
    setNewProtocol(protocol)
    setPairs(getDefaultSecretPairs(newProvider, protocol))
  }

  const updateSecretKind = (kind: 'llm' | 'custom') => {
    if (kind === secretKind) return
    invalidatePendingTest()
    setSecretKind(kind)
    if (kind === 'custom') {
      setNewProvider('custom')
      setNewProtocol('custom')
      setPairs([{ key: '', value: '' }])
    } else {
      setNewProvider('claude')
      setNewProtocol('anthropic_messages')
      setPairs(getDefaultSecretPairs('claude', 'anthropic_messages'))
    }
  }

  const openCreateDialog = (kind?: 'llm' | 'custom') => {
    if (!currentProjectAllowsWrite()) return
    createRunRef.current += 1
    testRunRef.current += 1
    resetCreateDraft()
    if (kind === 'custom') updateSecretKind('custom')
    setShowCreate(true)
  }

  const closeCreateDialog = () => {
    createRunRef.current += 1
    testRunRef.current += 1
    resetCreateDraft()
    setShowCreate(false)
  }

  // Deep-link: /managed/secrets?create=custom|llm opens the create dialog
  // pre-selected to the requested kind, then strips the param.
  useEffect(() => {
    const createKind = searchParams.get('create')
    if (createKind === 'custom' || createKind === 'llm') {
      openCreateDialog(createKind)
      router.replace('/managed/secrets')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const validPairs = pairs.filter((p) => p.key.trim())
  const canCreate = Boolean(
    newName.trim() && validPairs.length > 0 && (secretKind === 'custom' || testResult?.ok),
  )
  const buildSecretData = () => {
    const data: Record<string, string> = {}
    for (const p of validPairs) {
      data[p.key.trim()] = p.value
    }
    return data
  }
  const filteredSecrets = secrets.filter(
    (s) =>
      filterByCreatedTime(s.created_at, createdFilter) &&
      matchesSearch(searchQuery, [s.id, s.name]),
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  useEffect(() => {
    setDeleteTarget((target) => {
      if (!target) return null
      const current = secrets.find((secret) => secret.id === target.id) ?? null
      if (!current) {
        deleteRunRef.current += 1
      }
      return current
    })
  }, [secrets])

  const currentSecret = (secret: Secret | null) => {
    if (!secret) return null
    if (!isCurrentManagedScope(managedScopeRef.current)) return null
    if (!currentProjectAllowsWrite()) return null
    return (
      queryClient
        .getQueriesData<{ data?: Secret[] }>({
          queryKey: ['secrets', managedScopeRef.current, '/secrets'],
        })
        .flatMap(([, page]) => page?.data ?? [])
        .find((candidate) => candidate.id === secret.id) ?? null
    )
  }

  const handleCreate = async () => {
    if (!canCreate) return
    if (!currentProjectAllowsWrite()) return
    const action = nextScopedRun(createRunRef)
    if (!isCurrentScopedRun(createRunRef, action)) return
    const data = buildSecretData()
    const name = newName.trim()
    const provider = newProvider
    const protocol = newProtocol
    const isDefault = secrets.length === 0
    setCreating(true)
    try {
      await managedPost(
        '/secrets',
        {
          name,
          provider,
          protocol,
          data,
          is_default: isDefault,
        },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentScopedRun(createRunRef, action)) return
      resetCreateDraft()
      setShowCreate(false)
      queryClient.invalidateQueries({ queryKey: ['secrets', action.scope] })
    } catch (e) {
      if (!isCurrentScopedRun(createRunRef, action)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentScopedRun(createRunRef, action)) {
        setCreating(false)
      }
    }
  }

  const handleTestConnection = async () => {
    if (validPairs.length === 0) return
    if (!currentProjectAllowsWrite()) return
    const action = nextScopedRun(testRunRef)
    if (!isCurrentScopedRun(testRunRef, action)) return
    const provider = newProvider
    const protocol = newProtocol
    const data = buildSecretData()
    setTestingSecret(true)
    setTestResult(null)
    try {
      const result = await managedPost<SecretTestResult>(
        '/secrets/test',
        {
          provider,
          protocol,
          data,
        },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentScopedRun(testRunRef, action)) return
      setTestResult(result)
    } catch (e) {
      if (!isCurrentScopedRun(testRunRef, action)) return
      const error = parseApiError(e)
      setTestResult({
        ok: false,
        provider,
        protocol,
        message: error.message || t('managed.secrets.testFailed'),
        status: error.status,
      })
    } finally {
      if (isCurrentScopedRun(testRunRef, action)) {
        setTestingSecret(false)
      }
    }
  }

  const handleDelete = async () => {
    const target = currentSecret(deleteTarget)
    if (!target) {
      deleteRunRef.current += 1
      setDeleteTarget(null)
      return
    }
    const action = nextScopedRun(deleteRunRef)
    try {
      await managedDelete(
        apiResourcePath('secrets', target.id),
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentScopedRun(deleteRunRef, action)) return
      queryClient.invalidateQueries({ queryKey: ['secrets', action.scope] })
    } catch (e) {
      if (!isCurrentScopedRun(deleteRunRef, action)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentScopedRun(deleteRunRef, action)) {
        setDeleteTarget(null)
      }
    }
  }

  const handleSetDefault = async (secret: Secret) => {
    const target = currentSecret(secret)
    if (!target) return

    const action = nextScopedRun(defaultRunRef)
    try {
      await managedPost(
        apiResourcePath('secrets', target.id, 'default'),
        {},
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentScopedRun(defaultRunRef, action)) return
      queryClient.invalidateQueries({ queryKey: ['secrets', action.scope] })
    } catch (e) {
      if (!isCurrentScopedRun(defaultRunRef, action)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const columns: Column<Secret>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (s) => <MonoId id={s.id} />,
    },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => (
        <div className="flex items-center gap-2">
          <span className="font-medium text-foreground">{s.name}</span>
          {s.is_default && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
              <Check className="h-3 w-3" />
              {t('managed.secrets.default')}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'provider',
      header: t('managed.secrets.provider'),
      render: (s) =>
        isCustomSecretProvider(s.provider) ? (
          <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">
            {t('managed.secrets.kindCustom')}
          </Badge>
        ) : (
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary">{t('managed.secrets.kindLlm')}</Badge>
            <span className="text-xs text-muted-foreground">
              {getSecretProviderLabel(s.provider)}
            </span>
          </div>
        ),
    },
    {
      key: 'protocol',
      header: t('managed.secrets.protocol'),
      render: (s) => (
        <span className="text-xs text-muted-foreground">{s.protocol || 'custom'}</span>
      ),
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={s.created_at} />
        </span>
      ),
    },
  ]

  if (secretsIsError) {
    return (
      <ResourceErrorState
        error={secretsError}
        resource="secret"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['secrets', managedScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.secrets.title')}
        subtitle={t('managed.secrets.subtitle')}
        action={
          projectReadOnly ? null : (
            <Button size="sm" onClick={() => openCreateDialog()}>
              <Plus className="h-4 w-4" />
              {t('managed.secrets.new')}
            </Button>
          )
        }
      />
      <FilterBar
        searchPlaceholder={t('managed.search.secrets')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />
      <DataTable
        columns={columns}
        data={filteredSecrets}
        loading={secretsLoading}
        fetching={secretsFetching}
        onRowClick={(s) => router.push(`/managed/secrets/${s.id}`)}
        actionMenu={(s) =>
          projectReadOnly
            ? []
            : [
                ...(s.is_default
                  ? []
                  : [
                      {
                        label: t('managed.secrets.setDefault'),
                        icon: <Star className="h-4 w-4" />,
                        onClick: () => handleSetDefault(s),
                      },
                    ]),
                {
                  label: t('common.delete'),
                  onClick: () => {
                    if (!currentSecret(s)) return

                    deleteRunRef.current += 1
                    setDeleteTarget(s)
                  },
                  destructive: true,
                },
              ]
        }
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
        emptyMessage={t('managed.secrets.empty')}
      />

      <Dialog
        open={!projectReadOnly && showCreate}
        onOpenChange={(open) => {
          if (open) openCreateDialog()
          else closeCreateDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('managed.secrets.new')}</DialogTitle>
            <DialogDescription>{t('managed.secrets.createDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">{t('managed.secrets.name')}</label>
              <Input
                placeholder={t('managed.secrets.namePlaceholder')}
                value={newName}
                onChange={(e) => {
                  setTestResult(null)
                  setNewName(e.target.value)
                }}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/50 p-1">
              {(['llm', 'custom'] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => updateSecretKind(kind)}
                  className={[
                    'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    secretKind === kind
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground',
                  ].join(' ')}
                >
                  {kind === 'llm' ? t('managed.secrets.kindLlm') : t('managed.secrets.kindCustom')}
                </button>
              ))}
            </div>
            {secretKind === 'custom' && (
              <p className="text-xs text-muted-foreground">{t('managed.secrets.customHint')}</p>
            )}
            {secretKind === 'llm' && (
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] gap-2">
                <div className="space-y-1">
                  <label className="text-sm font-medium">{t('managed.secrets.provider')}</label>
                  <Select value={newProvider} onValueChange={updateProvider}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SECRET_PROVIDER_GROUPS.map((group) => (
                        <SelectGroup key={group.label}>
                          <SelectLabel className="flex items-center gap-2 px-2 py-2">
                            <span
                              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white"
                              style={{ backgroundColor: group.bgColor }}
                            >
                              {group.icon}
                            </span>
                            <span className="text-sm font-semibold text-foreground">
                              {t(group.labelKey, { defaultValue: group.label })}
                            </span>
                          </SelectLabel>
                          {group.options.map((provider, i) => {
                            const isLast = i === group.options.length - 1
                            const prefix = isLast ? '└' : '├'
                            return (
                              <SelectItem
                                key={provider.value}
                                value={provider.value}
                                className="pl-8 text-sm"
                              >
                                <span className="flex items-center gap-1.5">
                                  <span className="text-xs text-muted-foreground/50">{prefix}</span>
                                  {provider.label}
                                </span>
                              </SelectItem>
                            )
                          })}
                        </SelectGroup>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">{t('managed.secrets.protocol')}</label>
                  <Select value={newProtocol} onValueChange={updateProtocol}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SECRET_PROTOCOL_OPTIONS.map((protocol) => (
                        <SelectItem key={protocol.value} value={protocol.value}>
                          {protocol.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="h-10 w-10" />
              </div>
            )}
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('managed.secrets.dataLabel')}</label>
              {pairs.map((pair, i) => (
                <div
                  key={i}
                  className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] items-center gap-2"
                >
                  {secretKind === 'custom' ? (
                    <Input
                      placeholder={t('managed.secrets.customKeyPlaceholder')}
                      value={pair.key}
                      onChange={(e) => updatePair(i, 'key', e.target.value)}
                      className="min-w-0 font-mono text-sm"
                    />
                  ) : (
                    <SecretKeySelect
                      value={pair.key}
                      onChange={(v) => updatePair(i, 'key', v)}
                      placeholder={t('managed.secrets.keyPlaceholder')}
                      className="min-w-0"
                      provider={newProvider}
                      protocol={newProtocol}
                    />
                  )}
                  {isModelKey(pair.key) ? (
                    <SecretModelInput
                      value={pair.value}
                      onChange={(v) => updatePair(i, 'value', v)}
                      placeholder={t('managed.secrets.selectModel')}
                      className="min-w-0"
                    />
                  ) : (
                    <Input
                      placeholder={t('managed.secrets.valuePlaceholder')}
                      value={pair.value}
                      onChange={(e) => updatePair(i, 'value', e.target.value)}
                      className="min-w-0"
                      type={isSecretValueMaskedKey(pair.key) ? 'password' : 'text'}
                    />
                  )}
                  {pairs.length > 1 ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => removePair(i)}
                      className="h-10 w-10"
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  ) : (
                    <div className="h-10 w-10" />
                  )}
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={addPair}>
                <Plus className="mr-1 h-3 w-3" />
                {t('managed.secrets.addPair')}
              </Button>
              {testResult && (
                <div
                  className={[
                    'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                    testResult.ok
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border-destructive/20 bg-destructive/5 text-destructive',
                  ].join(' ')}
                >
                  {testResult.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  )}
                  <div className="min-w-0 space-y-1 break-words">
                    <div>
                      {testResult.ok
                        ? t('managed.secrets.testSucceeded')
                        : testResult.message || t('managed.secrets.testFailed')}
                      {testResult.status ? ` (HTTP ${testResult.status})` : ''}
                    </div>
                    {!testResult.ok && (testResult.endpoint || testResult.error_detail) && (
                      <div className="border-current/10 space-y-1 rounded border bg-background/70 p-2 font-mono text-xs text-foreground">
                        {testResult.endpoint && <div>endpoint: {testResult.endpoint}</div>}
                        {testResult.error_detail && (
                          <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words">
                            {testResult.error_detail}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            {secretKind === 'llm' && (
              <Button
                onClick={handleTestConnection}
                disabled={validPairs.length === 0 || testingSecret || creating}
              >
                {testingSecret ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Wifi className="h-4 w-4" />
                )}
                {testingSecret ? t('managed.secrets.testing') : t('managed.secrets.testConnection')}
              </Button>
            )}
            <Button
              onClick={handleCreate}
              disabled={!canCreate || projectReadOnly || creating || testingSecret}
            >
              {creating ? t('common.loading') : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!projectReadOnly && !!deleteTarget}
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', {
          name: deleteTarget?.name,
        })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => {
          deleteRunRef.current += 1
          setDeleteTarget(null)
        }}
      />
    </div>
  )
}
