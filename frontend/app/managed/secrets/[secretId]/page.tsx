'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, Eye, EyeOff, Save } from 'lucide-react'
import { managedGet, managedPut } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PageHeader, MonoId, RelativeTime, ResourceErrorState, SecretKeySelect, SecretModelInput } from '@/components/managed/shared'
import { getDefaultProtocol, isModelKey, normalizeSecretProvider, SECRET_PROTOCOL_OPTIONS, SECRET_PROVIDER_GROUPS } from '@/lib/managed/secret-keys'

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

export default function SecretDetailPage({ params }: { params: Promise<{ secretId: string }> }) {
  const { secretId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()

  const [pairs, setPairs] = useState<KVPair[]>([])
  const [provider, setProvider] = useState('custom')
  const [protocol, setProtocol] = useState('custom')
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)

  const { data: secret, isLoading, isError, error } = useQuery({
    queryKey: ['secret', secretId],
    queryFn: () => managedGet<SecretDetail>(`/secrets/${stripIdPrefix(secretId)}`),
    enabled: !!secretId,
    retry: shouldRetryManagedResourceError,
  })

  useEffect(() => {
    if (secret?.secret_data) {
      setProvider(normalizeSecretProvider(secret.provider))
      setProtocol(secret.protocol || 'custom')
      setPairs(Object.entries(secret.secret_data).map(([key, value]) => ({ key, value })))
      setDirty(false)
    }
  }, [secret])

  const updatePair = (index: number, field: 'key' | 'value', val: string) => {
    setPairs((prev) => prev.map((p, i) => (i === index ? { ...p, [field]: val } : p)))
    setDirty(true)
  }

  const removePair = (index: number) => {
    setPairs((prev) => prev.filter((_, i) => i !== index))
    setDirty(true)
  }

  const addPair = () => {
    setPairs((prev) => [...prev, { key: '', value: '' }])
    setDirty(true)
  }

  const updateProvider = (nextProvider: string) => {
    const nextProtocol = getDefaultProtocol(nextProvider)
    setProvider(nextProvider)
    setProtocol(nextProtocol)
    setDirty(true)
  }

  const updateProtocol = (nextProtocol: string) => {
    setProtocol(nextProtocol)
    setDirty(true)
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const data: Record<string, string> = {}
      for (const p of pairs) {
        if (p.key.trim()) {
          data[p.key.trim()] = p.value
        }
      }
      return managedPut(`/secrets/${stripIdPrefix(secretId)}`, { name: secret!.name, provider, protocol, data })
    },
    onSuccess: () => {
      setDirty(false)
      queryClient.invalidateQueries({ queryKey: ['secret', secretId] })
    },
    onError: (error) => {
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
              <ArrowLeft className="w-4 h-4 mr-1" />
              {t('common.back')}
            </Button>
            <Button
              size="sm"
              onClick={() => saveMutation.mutate()}
              disabled={!dirty || saveMutation.isPending}
            >
              <Save className="w-4 h-4 mr-1" />
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        }
      />

      <div className="flex items-center gap-1.5 text-sm text-muted-foreground mb-6">
        <MonoId id={secret.id || secretId} truncate={false} />
        <span>·</span>
        <RelativeTime date={secret.created_at} />
      </div>

      <div className="border border-border rounded-lg p-6 space-y-4">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] gap-2">
          <div className="space-y-1">
            <label className="text-sm font-medium">{t('managed.secrets.provider')}</label>
            <Select value={provider} onValueChange={updateProvider}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SECRET_PROVIDER_GROUPS.map((group) => (
                  <SelectGroup key={group.label}>
                    <SelectLabel className="flex items-center gap-2 px-2 py-2">
                      <span
                        className="w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold text-white shrink-0"
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
                        <SelectItem key={item.value} value={item.value} className="text-sm pl-8">
                          <span className="flex items-center gap-1.5">
                            <span className="text-muted-foreground/50 text-xs">{prefix}</span>
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
            <Select value={protocol} onValueChange={updateProtocol}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SECRET_PROTOCOL_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="h-10 w-10" />
        </div>
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">{t('managed.secrets.dataLabel')}</label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowValues(!showValues)}
          >
            {showValues ? <EyeOff className="w-4 h-4 mr-1" /> : <Eye className="w-4 h-4 mr-1" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>

        <div className="space-y-2">
          {pairs.map((pair, i) => (
            <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem] items-center gap-2">
              <SecretKeySelect
                value={pair.key}
                onChange={(v) => updatePair(i, 'key', v)}
                placeholder={t('managed.secrets.keyPlaceholder')}
                className="min-w-0"
                provider={provider}
                protocol={protocol}
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
                  className="min-w-0 font-mono text-sm"
                  type={showValues ? 'text' : 'password'}
                />
              )}
              <Button
                variant="ghost"
                size="icon"
                onClick={() => removePair(i)}
                className="h-10 w-10 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>

        <Button variant="outline" size="sm" onClick={addPair}>
          <Plus className="w-3 h-3 mr-1" />
          {t('managed.secrets.addPair')}
        </Button>
      </div>
    </div>
  )
}
