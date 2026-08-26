'use client'

import { AlertCircle, Check, Plus, RefreshCw } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCompatibleCredentials } from '@/hooks/managed/use-compatible-credentials'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { useTranslation } from '@/lib/i18n'
import { findProtocol, findProvider, getProtocol, getProvider } from '@/lib/managed/llm-catalog'
import { cn } from '@/lib/utils'
import type { CredentialId } from '@/types/entity-id'
import type { Credential } from '@/types/managed'

interface CompatibleCredentialPickerProps {
  engineId: string
  value: CredentialId | ''
  onChange: (value: CredentialId | '') => void
  onCreateRequested: () => void
  allowNone?: boolean
  disabled?: boolean
  conflictCredential?: Credential | null
  conflictValue?: string
  conflictMessage?: string
}

export function CompatibleCredentialPicker({
  engineId,
  value,
  onChange,
  onCreateRequested,
  allowNone = false,
  disabled = false,
  conflictCredential,
  conflictValue,
  conflictMessage,
}: CompatibleCredentialPickerProps) {
  const { t } = useTranslation()
  const query = useCompatibleCredentials({ engineId, enabled: Boolean(engineId) })
  const catalogQuery = useLlmCatalog()

  if (!engineId) {
    return <p className="text-sm text-muted-foreground">{t('managed.llm.chooseEngineFirst')}</p>
  }
  if (query.isLoading || catalogQuery.isLoading) {
    return (
      <div className="space-y-2" aria-label={t('managed.llm.loadingConfigurations')}>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }
  if (query.isError || catalogQuery.isError || !catalogQuery.data) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between gap-3">
          <span>{t('managed.llm.configurationLoadFailed')}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void query.refetch()
              void catalogQuery.refetch()
            }}
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            {t('common.retry')}
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  const options = query.data ?? []
  const conflictMetadata = conflictCredential
    ? [
        conflictCredential.provider
          ? (findProvider(catalogQuery.data, conflictCredential.provider)?.display_name ??
            conflictCredential.provider)
          : t('managed.llm.unknownProvider'),
        conflictCredential.protocol
          ? (findProtocol(catalogQuery.data, conflictCredential.protocol)?.display_name ??
            conflictCredential.protocol)
          : t('managed.llm.unknownProtocol'),
        conflictCredential.model,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''
  return (
    <div className="space-y-3">
      {(conflictCredential || conflictValue) && conflictMessage ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            <p>{conflictMessage}</p>
            <p className="mt-1 font-medium">{conflictCredential?.name ?? conflictValue}</p>
            {conflictMetadata ? (
              <p className="mt-1 text-xs opacity-80">{conflictMetadata}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {options.length > 0 ? (
        <div className="grid gap-2" role="radiogroup" aria-label={t('managed.llm.configuration')}>
          {allowNone ? (
            <button
              type="button"
              role="radio"
              aria-checked={!value}
              disabled={disabled}
              onClick={() => onChange('')}
              className={cn(
                'flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors',
                !value
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-border hover:bg-muted/50',
              )}
            >
              <span
                className={cn(
                  'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
                  !value ? 'border-primary bg-primary text-primary-foreground' : 'border-input',
                )}
              >
                {!value ? <Check className="h-3 w-3" /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">{t('managed.agents.edit.noSelection')}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {t('managed.llm.noConfigurationHint')}
                </span>
              </span>
            </button>
          ) : null}
          {options.map((credential) => {
            const selected = credential.id === value
            const provider = credential.provider
              ? getProvider(catalogQuery.data, credential.provider).display_name
              : t('managed.llm.unknownProvider')
            const protocol = credential.protocol
              ? getProtocol(catalogQuery.data, credential.protocol).display_name
              : t('managed.llm.unknownProtocol')
            return (
              <button
                key={credential.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => onChange(credential.id)}
                className={cn(
                  'flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors',
                  selected
                    ? 'border-primary bg-primary/5 ring-1 ring-primary'
                    : 'border-border hover:bg-muted/50',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
                    selected ? 'border-primary bg-primary text-primary-foreground' : 'border-input',
                  )}
                >
                  {selected ? <Check className="h-3 w-3" /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{credential.name}</span>
                    {credential.is_default ? (
                      <Badge variant="secondary">{t('managed.llm.defaultForProtocol')}</Badge>
                    ) : null}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {provider} · {protocol}
                    {credential.model ? ` · ${credential.model}` : ''}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed p-5 text-center">
          <p className="text-sm font-medium">{t('managed.llm.noCompatibleConfigurations')}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t('managed.llm.noCompatibleConfigurationsHint')}
          </p>
        </div>
      )}

      <Button type="button" variant="outline" onClick={onCreateRequested} disabled={disabled}>
        <Plus className="mr-1.5 h-4 w-4" />
        {t('managed.llm.createConfiguration')}
      </Button>
    </div>
  )
}
