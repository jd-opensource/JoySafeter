'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, Eye, EyeOff, Save } from 'lucide-react'
import { managedGet, managedPut } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
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
  PageHeader,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  SecretKeySelect,
  SecretModelInput,
} from '@/components/managed/shared'
import {
  getDefaultProtocol,
  isModelKey,
  isSecretValueMaskedKey,
  normalizeSecretProvider,
  SECRET_PROTOCOL_OPTIONS,
  SECRET_PROVIDER_GROUPS,
} from '@/lib/managed/secret-keys'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface SecretDetail {
  id: string
  name: string
  provider: string
  protocol: string
  secret_data: Record<string, string>
  created_at: string
  updated_at: string
}

interface KVPair {
  key: string
  value: string
}

interface SaveSecretVariables {
  secretId: string
  payload: {
    name: string
    provider: string
    protocol: string
    data: Record<string, string>
  }
  runId: number
  scope: string
}

export default function SecretDetailPage({ params }: { params: Promise<{ secretId: string }> }) {
  const { secretId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const operationScope = `${managedScope}:${secretId ?? ''}`
  const saveRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const hydratedSecretScopeRef = useRef<string | null>(null)

  const [pairs, setPairs] = useState<KVPair[]>([])
  const [provider, setProvider] = useState('custom')
  const [protocol, setProtocol] = useState('custom')
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)

  const {
    data: secret,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['secret', managedScope, secretId],
    queryFn: () => managedGet<SecretDetail>(`/secrets/${stripIdPrefix(secretId)}`),
    enabled: !!secretId,
    retry: shouldRetryManagedResourceError,
  })

  useEffect(() => {
    if (operationScopeRef.current !== operationScope) {
      operationScopeRef.current = operationScope
      saveRunRef.current += 1
    }
  }, [operationScope])

  useEffect(
    () => () => {
      saveRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (secret?.secret_data) {
      const shouldHydrate = !dirty || hydratedSecretScopeRef.current !== operationScope
      if (!shouldHydrate) return

      setProvider(normalizeSecretProvider(secret.provider))
      setProtocol(secret.protocol || 'custom')
      setPairs(Object.entries(secret.secret_data).map(([key, value]) => ({ key, value })))
      hydratedSecretScopeRef.current = operationScope
      setDirty(false)
    }
  }, [dirty, operationScope, secret])

  const updatePair = (index: number, field: 'key' | 'value', val: string) => {
    if (!currentProjectAllowsWrite()) return
    setPairs((prev) => prev.map((p, i) => (i === index ? { ...p, [field]: val } : p)))
    setDirty(true)
  }

  const removePair = (index: number) => {
    if (!currentProjectAllowsWrite()) return
    setPairs((prev) => prev.filter((_, i) => i !== index))
    setDirty(true)
  }

  const addPair = () => {
    if (!currentProjectAllowsWrite()) return
    setPairs((prev) => [...prev, { key: '', value: '' }])
    setDirty(true)
  }

  const updateProvider = (nextProvider: string) => {
    if (!currentProjectAllowsWrite()) return
    const nextProtocol = getDefaultProtocol(nextProvider)
    setProvider(nextProvider)
    setProtocol(nextProtocol)
    setDirty(true)
  }

  const updateProtocol = (nextProtocol: string) => {
    if (!currentProjectAllowsWrite()) return
    setProtocol(nextProtocol)
    setDirty(true)
  }

  const buildSavePayload = (): SaveSecretVariables['payload'] => {
    const data: Record<string, string> = {}
    for (const p of pairs) {
      if (p.key.trim()) {
        data[p.key.trim()] = p.value
      }
    }
    return {
      name: secret!.name,
      provider,
      protocol,
      data,
    }
  }

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}:${secretId ?? ''}`
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}`
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const currentSecretDetail = () => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const current = queryClient.getQueryData<SecretDetail>([
      'secret',
      getCurrentManagedScope(),
      secretId,
    ])
    return current?.id === secretId ? current : null
  }

  const isCurrentSaveRun = (runId: number, scope: string) =>
    saveRunRef.current === runId &&
    operationScopeRef.current === scope &&
    getCurrentOperationScope() === scope &&
    currentProjectAllowsWrite()

  const saveMutation = useMutation({
    mutationFn: async ({ secretId, payload, runId, scope }: SaveSecretVariables) => {
      if (!isCurrentSaveRun(runId, scope)) return undefined
      return managedPut(`/secrets/${stripIdPrefix(secretId)}`, payload)
    },
    onSuccess: (_data, { secretId, runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      setDirty(false)
      queryClient.invalidateQueries({ queryKey: ['secret', managedScope, secretId] })
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  if (isLoading) {
    return <div className="p-8 text-muted-foreground">{t('common.loading')}</div>
  }

  if (isError || !secret) {
    return (
      <ResourceErrorState
        error={error}
        resource="secret"
        backLabel={t('managed.secrets.backToList')}
        onBack={() => router.push('/managed/secrets')}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={secret.name || secretId}
        breadcrumb={[
          { label: t('managed.secrets.title'), to: '/managed/secrets' },
          { label: secret.name || secretId },
        ]}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => router.push('/managed/secrets')}>
              <ArrowLeft className="mr-1 h-4 w-4" />
              {t('common.back')}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                const current = currentSecretDetail()
                if (!current) return
                const runId = saveRunRef.current + 1
                saveRunRef.current = runId
                saveMutation.mutate({
                  secretId: current.id,
                  payload: { ...buildSavePayload(), name: current.name },
                  runId,
                  scope: operationScopeRef.current,
                })
              }}
              disabled={!dirty || projectReadOnly || saveMutation.isPending}
            >
              <Save className="mr-1 h-4 w-4" />
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        }
      />

      <div className="mb-6 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={secret.id || secretId} truncate={false} />
        <span>·</span>
        <RelativeTime date={secret.created_at} />
      </div>

      <div className="space-y-4 rounded-lg border border-border p-6">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] gap-2">
          <div className="space-y-1">
            <label className="text-sm font-medium">{t('managed.secrets.provider')}</label>
            <Select value={provider} onValueChange={updateProvider} disabled={projectReadOnly}>
              <SelectTrigger disabled={projectReadOnly}>
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
                    {group.options.map((item, i) => {
                      const isLast = i === group.options.length - 1
                      const prefix = isLast ? '└' : '├'
                      return (
                        <SelectItem key={item.value} value={item.value} className="pl-8 text-sm">
                          <span className="flex items-center gap-1.5">
                            <span className="text-xs text-muted-foreground/50">{prefix}</span>
                            {item.label}
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
            <Select value={protocol} onValueChange={updateProtocol} disabled={projectReadOnly}>
              <SelectTrigger disabled={projectReadOnly}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SECRET_PROTOCOL_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="h-10 w-10" />
        </div>
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">{t('managed.secrets.dataLabel')}</label>
          <Button variant="ghost" size="sm" onClick={() => setShowValues(!showValues)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>

        <div className="space-y-2">
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
                provider={provider}
                protocol={protocol}
                disabled={projectReadOnly}
              />
              {isModelKey(pair.key) ? (
                <SecretModelInput
                  value={pair.value}
                  onChange={(v) => updatePair(i, 'value', v)}
                  placeholder={t('managed.secrets.selectModel')}
                  className="min-w-0"
                  disabled={projectReadOnly}
                />
              ) : (
                <Input
                  placeholder={t('managed.secrets.valuePlaceholder')}
                  value={pair.value}
                  onChange={(e) => updatePair(i, 'value', e.target.value)}
                  className="min-w-0 font-mono text-sm"
                  type={!isSecretValueMaskedKey(pair.key) || showValues ? 'text' : 'password'}
                  disabled={projectReadOnly}
                />
              )}
              {projectReadOnly ? (
                <div className="h-10 w-10" />
              ) : (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removePair(i)}
                  className="h-10 w-10 text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </div>

        {!projectReadOnly && (
          <Button variant="outline" size="sm" onClick={addPair}>
            <Plus className="mr-1 h-3 w-3" />
            {t('managed.secrets.addPair')}
          </Button>
        )}
      </div>
    </div>
  )
}
