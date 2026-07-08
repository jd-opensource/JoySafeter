'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { Check, CheckCircle2, Loader2, Plus, Star, Trash2, Wifi, XCircle } from 'lucide-react'
import { managedPost, managedDelete } from '@/lib/api-client'
import { parseApiError, toastOperationError } from '@/lib/managed/errors'
import type { Secret } from '@/types/managed'
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

export default function SecretListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
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
  const [newProvider, setNewProvider] = useState('claude')
  const [newProtocol, setNewProtocol] = useState('anthropic_messages')
  const [pairs, setPairs] = useState<KVPair[]>([{ key: '', value: '' }])
  const [creating, setCreating] = useState(false)
  const [testingSecret, setTestingSecret] = useState(false)
  const [testResult, setTestResult] = useState<SecretTestResult | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const updatePair = (index: number, field: 'key' | 'value', val: string) => {
    setTestResult(null)
    setPairs((prev) => prev.map((p, i) => (i === index ? { ...p, [field]: val } : p)))
  }

  const removePair = (index: number) => {
    setTestResult(null)
    setPairs((prev) => prev.filter((_, i) => i !== index))
  }

  const addPair = () => {
    setTestResult(null)
    setPairs((prev) => [...prev, { key: '', value: '' }])
  }

  const updateProvider = (provider: string) => {
    const nextProtocol = getDefaultProtocol(provider)
    setTestResult(null)
    setNewProvider(provider)
    setNewProtocol(nextProtocol)
    setPairs(getDefaultSecretPairs(provider, nextProtocol))
  }

  const updateProtocol = (protocol: string) => {
    setTestResult(null)
    setNewProtocol(protocol)
    setPairs(getDefaultSecretPairs(newProvider, protocol))
  }

  const openCreateDialog = () => {
    setNewName('')
    setNewProvider('claude')
    setNewProtocol('anthropic_messages')
    setPairs(getDefaultSecretPairs('claude', 'anthropic_messages'))
    setTestResult(null)
    setShowCreate(true)
  }

  const validPairs = pairs.filter((p) => p.key.trim())
  const canCreate = Boolean(newName.trim() && validPairs.length > 0 && testResult?.ok)
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

  const handleCreate = async () => {
    if (!canCreate) return
    setCreating(true)
    try {
      const data = buildSecretData()
      await managedPost('/secrets', {
        name: newName.trim(),
        provider: newProvider,
        protocol: newProtocol,
        data,
        is_default: secrets.length === 0,
      })
      setNewName('')
      setNewProvider('claude')
      setNewProtocol('anthropic_messages')
      setPairs([{ key: '', value: '' }])
      setTestResult(null)
      setShowCreate(false)
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      setCreating(false)
    }
  }

  const handleTestConnection = async () => {
    if (validPairs.length === 0) return
    setTestingSecret(true)
    setTestResult(null)
    try {
      const result = await managedPost<SecretTestResult>('/secrets/test', {
        provider: newProvider,
        protocol: newProtocol,
        data: buildSecretData(),
      })
      setTestResult(result)
    } catch (e) {
      const error = parseApiError(e)
      setTestResult({
        ok: false,
        provider: newProvider,
        protocol: newProtocol,
        message: error.message || t('managed.secrets.testFailed'),
        status: error.status,
      })
    } finally {
      setTestingSecret(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await managedDelete(`/secrets/${deleteTarget.id}`)
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const handleSetDefault = async (secret: Secret) => {
    try {
      await managedPost(`/secrets/${secret.id}/default`, {})
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
    } catch (e) {
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
      render: (s) => (
        <span className="text-xs text-muted-foreground">{getSecretProviderLabel(s.provider)}</span>
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
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['secrets'] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.secrets.title')}
        subtitle={t('managed.secrets.subtitle')}
        action={
          <Button size="sm" onClick={openCreateDialog}>
            <Plus className="h-4 w-4" />
            {t('managed.secrets.new')}
          </Button>
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
        actionMenu={(s) => [
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
            onClick: () => setDeleteTarget(s),
            destructive: true,
          },
        ]}
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
        open={showCreate}
        onOpenChange={(open) => {
          setShowCreate(open)
          if (!open) {
            setTestResult(null)
          }
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
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('managed.secrets.dataLabel')}</label>
              {pairs.map((pair, i) => (
                <div
                  key={i}
                  className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] items-center gap-2"
                >
                  <SecretKeySelect
                    value={pair.key}
                    onChange={(v) => updatePair(i, 'key', v)}
                    placeholder={t('managed.secrets.keyPlaceholder')}
                    className="min-w-0"
                    provider={newProvider}
                    protocol={newProtocol}
                  />
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
                      <div className="space-y-1 rounded border border-current/10 bg-background/70 p-2 font-mono text-xs text-foreground">
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
            <Button
              onClick={handleCreate}
              disabled={!canCreate || creating || testingSecret}
            >
              {creating ? t('common.loading') : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', {
          name: deleteTarget?.name,
        })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
