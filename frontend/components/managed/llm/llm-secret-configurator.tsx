'use client'

import { AlertCircle, CheckCircle2, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { FormFieldError, FormFieldLabel } from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import {
  type AnthropicAuthScheme,
  inferSchemeFromValues,
  resolveAnthropicScheme,
} from '@/lib/managed/anthropic-auth'
import {
  getAllProviderProtocolOptions,
  getProviderProtocolOptions,
  stableConnectionFingerprint,
} from '@/lib/managed/llm-catalog'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import { cn } from '@/lib/utils'
import type { LlmCredentialField } from '@/types/llm'
import type { SecretDetail } from '@/types/managed'

interface LlmSecretConfiguratorProps {
  initialEngineId?: string
  onCreated: (secret: SecretDetail) => void
  onCancel?: () => void
  className?: string
}

function valuesForProfile(
  fields: LlmCredentialField[],
  previous: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.key, previous[field.key] ?? '']))
}

function validateValues(
  fields: LlmCredentialField[],
  requiredAnyOf: string[][],
  values: Record<string, string>,
): string | null {
  const missing = fields.find((field) => field.required && !values[field.key]?.trim())
  if (missing) return `${missing.label} is required.`
  for (const group of requiredAnyOf) {
    if (!group.some((key) => values[key]?.trim())) {
      const labels = group.map((key) => fields.find((field) => field.key === key)?.label ?? key)
      return `Provide one of: ${labels.join(' / ')}.`
    }
  }
  return null
}

function fieldInputType(field: LlmCredentialField) {
  if (field.type === 'secret') return 'password'
  if (field.type === 'url') return 'url'
  return 'text'
}

export function LlmSecretConfigurator({
  initialEngineId,
  onCreated,
  onCancel,
  className,
}: LlmSecretConfiguratorProps) {
  const { t } = useTranslation()
  const catalogQuery = useLlmCatalog()
  const engineId = initialEngineId ?? ''
  const [providerId, setProviderId] = useState('')
  const [protocolId, setProtocolId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [authScheme, setAuthScheme] = useState<AnthropicAuthScheme>('auto')
  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [testedFingerprint, setTestedFingerprint] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [testMessage, setTestMessage] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [creating, setCreating] = useState(false)
  const { readOnly, beginAction, isCurrentAction, bumpRun } = useScopedActions({
    onReset: () => {
      setTesting(false)
      setCreating(false)
      setValidationError(null)
      setRequestError(null)
      setTestMessage(null)
      onCancel?.()
    },
  })

  const options = useMemo(() => {
    if (!catalogQuery.data) return []
    return engineId
      ? getProviderProtocolOptions(catalogQuery.data, engineId)
      : getAllProviderProtocolOptions(catalogQuery.data)
  }, [catalogQuery.data, engineId])
  const providerOptions = useMemo(() => {
    const seen = new Set<string>()
    return options.filter((option) => {
      if (seen.has(option.providerId)) return false
      seen.add(option.providerId)
      return true
    })
  }, [options])
  const protocolOptions = useMemo(
    () => options.filter((option) => option.providerId === providerId),
    [options, providerId],
  )
  const selectedOption = useMemo(
    () =>
      options.find(
        (option) => option.providerId === providerId && option.protocolId === protocolId,
      ) ?? null,
    [options, protocolId, providerId],
  )
  const currentFingerprint = stableConnectionFingerprint({ providerId, protocolId, values })
  const connectionTestIsFresh =
    testedFingerprint !== null && testedFingerprint === currentFingerprint
  const connectionTestIsStale = testedFingerprint !== null && !connectionTestIsFresh
  const isAnthropic = selectedOption?.credentialProfile.id === 'anthropic_standard'

  useEffect(() => {
    if (selectedOption) return
    const currentProviderOptions = options.filter((option) => option.providerId === providerId)
    if (providerId && currentProviderOptions.length === 1) {
      setProtocolId(currentProviderOptions[0].protocolId)
      return
    }
    if (providerId && currentProviderOptions.length > 1) {
      setProtocolId('')
      return
    }
    if (options.length === 1) {
      setProviderId(options[0].providerId)
      setProtocolId(options[0].protocolId)
      return
    }
    setProviderId('')
    setProtocolId('')
  }, [options, providerId, selectedOption])

  useEffect(() => {
    let inferred: Record<string, string> = {}
    setValues((previous) => {
      inferred = selectedOption
        ? valuesForProfile(selectedOption.credentialProfile.fields, previous)
        : {}
      return inferred
    })
    setAuthScheme(inferSchemeFromValues(inferred))
    setValidationError(null)
    setRequestError(null)
    setTestMessage(null)
    setShowAdvanced(false)
  }, [selectedOption])

  if (catalogQuery.isLoading) {
    return (
      <div className="space-y-3" aria-label={t('managed.llm.loadingCatalog')}>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (catalogQuery.isError || !catalogQuery.data) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between gap-3">
          <span>{t('managed.llm.catalogLoadFailed')}</span>
          <Button type="button" variant="outline" size="sm" onClick={() => catalogQuery.refetch()}>
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            {t('common.retry')}
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  const visibleFields =
    selectedOption?.credentialProfile.fields.filter(
      (field) =>
        (!field.advanced || showAdvanced) &&
        !(isAnthropic && field.key === 'ANTHROPIC_AUTH_TOKEN'),
    ) ?? []
  const advancedFieldCount =
    selectedOption?.credentialProfile.fields.filter(
      (field) => field.advanced && !(isAnthropic && field.key === 'ANTHROPIC_AUTH_TOKEN'),
    ).length ?? 0

  const runValidation = () => {
    if (!providerId || !protocolId || !selectedOption) {
      setValidationError(t('managed.llm.chooseProviderProtocol'))
      return false
    }
    const error = validateValues(
      selectedOption.credentialProfile.fields,
      selectedOption.credentialProfile.required_any_of,
      values,
    )
    setValidationError(error)
    return !error
  }

  const testConnection = async () => {
    if (!runValidation()) return
    const action = beginAction()
    if (!action) {
      onCancel?.()
      return
    }
    const fingerprint = currentFingerprint
    setTesting(true)
    setRequestError(null)
    setTestMessage(null)
    try {
      const result = await managedPost<{ ok: boolean; message: string }>(
        '/credentials/test',
        {
          provider: providerId,
          protocol: protocolId,
          data: values,
          auth_scheme: isAnthropic ? authScheme : undefined,
        },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      if (!result.ok) {
        setRequestError(result.message || t('managed.llm.connectionFailed'))
        return
      }
      setTestedFingerprint(fingerprint)
      setTestMessage(result.message)
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      setRequestError(error instanceof Error ? error.message : t('managed.llm.connectionFailed'))
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setTesting(false)
    }
  }

  const createSecret = async () => {
    if (!name.trim()) {
      setValidationError(t('managed.llm.nameRequired'))
      return
    }
    if (!runValidation()) return
    const action = beginAction()
    if (!action) {
      onCancel?.()
      return
    }
    setCreating(true)
    setRequestError(null)
    try {
      const response = await managedPost<unknown>(
        '/credentials',
        {
          kind: 'model',
          name: name.trim(),
          provider: providerId,
          protocol: protocolId,
          data: values,
          is_default: isDefault,
          auth_scheme: isAnthropic ? authScheme : undefined,
        },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      onCreated(parseSecretDetailResponse(response))
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      setRequestError(error instanceof Error ? error.message : t('managed.llm.createFailed'))
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setCreating(false)
    }
  }

  return (
    <div className={cn('space-y-5', className)}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <FormFieldLabel htmlFor="llm-provider" required>
            {t('managed.llm.provider')}
          </FormFieldLabel>
          <select
            id="llm-provider"
            aria-label={t('managed.llm.provider')}
            value={providerId}
            disabled={readOnly}
            onChange={(event) => {
              const nextProvider = event.target.value
              const nextProtocols = options.filter((option) => option.providerId === nextProvider)
              setProviderId(nextProvider)
              setProtocolId(nextProtocols.length === 1 ? nextProtocols[0].protocolId : '')
            }}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">{t('managed.llm.chooseProvider')}</option>
            {providerOptions.map((option) => (
              <option key={option.providerId} value={option.providerId}>
                {option.provider.display_name}
              </option>
            ))}
          </select>
        </div>

        {protocolOptions.length > 1 ? (
          <div className="space-y-2">
            <FormFieldLabel htmlFor="llm-protocol" required>
              {t('managed.llm.protocol')}
            </FormFieldLabel>
            <select
              id="llm-protocol"
              aria-label={t('managed.llm.protocol')}
              value={protocolId}
              disabled={readOnly}
              onChange={(event) => setProtocolId(event.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">{t('managed.llm.chooseProtocol')}</option>
              {protocolOptions.map((option) => (
                <option key={option.protocolId} value={option.protocolId}>
                  {option.protocol.display_name}
                </option>
              ))}
            </select>
            {selectedOption ? (
              <p className="text-xs text-muted-foreground">{selectedOption.protocol.description}</p>
            ) : null}
          </div>
        ) : null}
      </div>

      {selectedOption ? (
        <div className="space-y-4 rounded-xl border bg-muted/20 p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {visibleFields.map((field) => (
              <div key={field.key} className="space-y-2">
                <FormFieldLabel htmlFor={`llm-field-${field.key}`} required={field.required}>
                  {field.label}
                </FormFieldLabel>
                {field.type === 'select' ? (
                  <select
                    id={`llm-field-${field.key}`}
                    aria-label={field.label}
                    value={values[field.key] ?? ''}
                    disabled={readOnly}
                    onChange={(event) =>
                      setValues((current) => ({ ...current, [field.key]: event.target.value }))
                    }
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">{t('common.select')}</option>
                    {field.options.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id={`llm-field-${field.key}`}
                    aria-label={field.label}
                    type={fieldInputType(field)}
                    value={values[field.key] ?? ''}
                    disabled={readOnly}
                    placeholder={field.placeholder ?? undefined}
                    autoComplete={field.type === 'secret' ? 'new-password' : undefined}
                    onChange={(event) =>
                      setValues((current) => ({ ...current, [field.key]: event.target.value }))
                    }
                  />
                )}
                {field.help_text ? (
                  <p className="text-xs text-muted-foreground">{field.help_text}</p>
                ) : null}
                {showAdvanced ? (
                  <code className="block text-[11px] text-muted-foreground">{field.key}</code>
                ) : null}
              </div>
            ))}
          </div>
          {isAnthropic ? (
            <div className="space-y-2">
              <FormFieldLabel htmlFor="llm-anthropic-auth-scheme">
                {t('managed.llm.authScheme')}
              </FormFieldLabel>
              <select
                id="llm-anthropic-auth-scheme"
                aria-label={t('managed.llm.authScheme')}
                value={authScheme}
                disabled={readOnly}
                onChange={(event) => setAuthScheme(event.target.value as AnthropicAuthScheme)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="auto">{t('managed.llm.authSchemeAuto')}</option>
                <option value="xapikey">{t('managed.llm.authSchemeApiKey')}</option>
                <option value="bearer">{t('managed.llm.authSchemeBearer')}</option>
              </select>
              <p className="text-xs text-muted-foreground">
                {resolveAnthropicScheme(values['ANTHROPIC_BASE_URL'] ?? '', authScheme) === 'bearer'
                  ? t('managed.llm.authSchemePreviewBearer')
                  : t('managed.llm.authSchemePreviewApiKey')}
              </p>
            </div>
          ) : null}
          {advancedFieldCount > 0 ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={readOnly}
              onClick={() => setShowAdvanced((value) => !value)}
            >
              {showAdvanced ? t('managed.llm.hideAdvanced') : t('managed.llm.showAdvanced')}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="space-y-2">
          <FormFieldLabel htmlFor="llm-secret-name" required>
            {t('managed.llm.configurationName')}
          </FormFieldLabel>
          <Input
            id="llm-secret-name"
            value={name}
            disabled={readOnly}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('managed.llm.configurationNamePlaceholder')}
          />
        </div>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isDefault}
            disabled={readOnly}
            onChange={(event) => setIsDefault(event.target.checked)}
          />
          {t('managed.llm.setAsProtocolDefault')}
        </label>
      </div>

      <FormFieldError message={validationError ?? undefined} />
      {requestError ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{requestError}</AlertDescription>
        </Alert>
      ) : null}
      {connectionTestIsFresh ? (
        <Alert variant="success">
          <CheckCircle2 className="h-4 w-4" />
          <AlertDescription>{t('managed.llm.connectionVerified')}</AlertDescription>
        </Alert>
      ) : null}
      {connectionTestIsStale ? (
        <p className="text-sm text-amber-700">{t('managed.llm.connectionTestStale')}</p>
      ) : null}
      {testMessage && !connectionTestIsFresh ? (
        <p className="text-sm text-muted-foreground">{testMessage}</p>
      ) : null}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        {onCancel ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              bumpRun()
              onCancel()
            }}
            disabled={testing || creating}
          >
            {t('common.cancel')}
          </Button>
        ) : null}
        <Button
          type="button"
          variant="outline"
          onClick={testConnection}
          disabled={testing || creating || readOnly}
        >
          {testing ? t('managed.llm.testing') : t('managed.llm.testConnection')}
        </Button>
        <Button type="button" onClick={createSecret} disabled={testing || creating || readOnly}>
          {creating ? t('managed.llm.creating') : t('managed.llm.createConfiguration')}
        </Button>
      </div>
    </div>
  )
}
