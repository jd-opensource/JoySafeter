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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PageHeader, MonoId, RelativeTime, ResourceErrorState, SecretKeySelect } from '@/components/managed/shared'
import { getDefaultSecretPairs, MODEL_OPTIONS, SECRET_PROTOCOL_OPTIONS, SECRET_PROVIDER_OPTIONS } from '@/lib/managed/secret-keys'

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
      setProvider(secret.provider || 'custom')
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
    const nextProtocol = nextProvider === 'anthropic' ? 'anthropic' : nextProvider === 'openai' ? 'openai_compatible' : 'custom'
    setProvider(nextProvider)
    setProtocol(nextProtocol)
    setPairs(getDefaultSecretPairs(nextProvider, nextProtocol))
    setDirty(true)
  }

  const updateProtocol = (nextProtocol: string) => {
    setProtocol(nextProtocol)
    setPairs(getDefaultSecretPairs(provider, nextProtocol))
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
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-sm font-medium">{t('managed.secrets.provider')}</label>
            <Select value={provider} onValueChange={updateProvider}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SECRET_PROVIDER_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
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
            <div key={i} className="flex items-center gap-2">
              <SecretKeySelect
                value={pair.key}
                onChange={(v) => updatePair(i, 'key', v)}
                placeholder={t('managed.secrets.keyPlaceholder')}
              />
              {pair.key === 'ANTHROPIC_MODEL' ? (
                <Select value={pair.value} onValueChange={(v) => updatePair(i, 'value', v)}>
                  <SelectTrigger className="flex-1 font-mono text-sm">
                    <SelectValue placeholder={t('managed.secrets.selectModel')} />
                  </SelectTrigger>
                  <SelectContent>
                    {MODEL_OPTIONS.map((m) => (
                      <SelectItem key={m} value={m} className="font-mono text-sm">{m}</SelectItem>
                    ))}
                    {pair.value && !MODEL_OPTIONS.includes(pair.value) && (
                      <SelectItem value={pair.value} className="font-mono text-sm">{pair.value}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  placeholder={t('managed.secrets.valuePlaceholder')}
                  value={pair.value}
                  onChange={(e) => updatePair(i, 'value', e.target.value)}
                  className="flex-1 font-mono text-sm"
                  type={showValues ? 'text' : 'password'}
                />
              )}
              <Button
                variant="ghost"
                size="icon"
                onClick={() => removePair(i)}
                className="text-muted-foreground hover:text-destructive"
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
