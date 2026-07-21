'use client'

import type { Dispatch, SetStateAction } from 'react'

import { FieldHelp } from '@/components/managed/shared/field-help'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTranslation } from '@/lib/i18n'
import { isCustomSecretProvider } from '@/lib/managed/secret-keys'
import type { EnvironmentEgressService, Secret } from '@/types/managed'

export type EgressServiceForm = {
  name: string
  baseUrl: string
  credentialRef: string
  authType: 'bearer' | 'api_key' | 'cookie'
  secretKey: string
  header: string
  allowedPaths: string
}

export type EgressServiceErrorField = 'name' | 'baseUrl' | 'credentialRef' | 'secretKey'
export type EgressServiceErrors = Record<number, Partial<Record<EgressServiceErrorField, string>>>

export const emptyEgressService = (): EgressServiceForm => ({
  name: '',
  baseUrl: '',
  credentialRef: '',
  authType: 'bearer',
  secretKey: '',
  header: '',
  allowedPaths: '',
})

const egressInjectedHeaderExample = (service: EgressServiceForm) => {
  if (service.authType === 'api_key') {
    const header = service.header.trim() || 'x-api-key'
    return `${header}: <value>`
  }
  if (service.authType === 'cookie') {
    const key = service.secretKey.trim() || 'COOKIE_HEADER'
    return `Cookie: <${key}>`
  }
  return `Authorization: Bearer <value>`
}

// Skill 可直接用 http 真实地址访问（scheme 用 http，Envoy 明文侧注入凭证再 TLS 回源）。
const egressHttpDirectUrl = (baseUrl: string) => {
  const trimmed = baseUrl.trim()
  if (!trimmed) return 'http://crm.example.com/api/'
  return trimmed.replace(/^https:\/\//i, 'http://')
}

const defaultsForAuthType = (authType: EgressServiceForm['authType']) => {
  if (authType === 'api_key') {
    return { authType, secretKey: '', header: 'x-api-key' }
  }
  if (authType === 'cookie') {
    return { authType, secretKey: 'COOKIE_HEADER', header: '' }
  }
  return { authType, secretKey: '', header: '' }
}

const secretKeysFor = (secret?: Secret) => secret?.keys || Object.keys(secret?.data || {})

const preferredSecretKey = (keys: string[], authType: EgressServiceForm['authType']) => {
  if (keys.length === 0) return authType === 'cookie' ? 'COOKIE_HEADER' : ''
  const normalized = new Map(keys.map((key) => [key.toUpperCase(), key]))
  if (authType === 'cookie') {
    return normalized.get('COOKIE_HEADER') || keys[0]
  }
  if (authType === 'api_key') {
    return normalized.get('API_KEY') || normalized.get('X_API_KEY') || keys[0]
  }
  return normalized.get('ACCESS_TOKEN') || normalized.get('TOKEN') || keys[0]
}

export const serviceToForm = (service: EnvironmentEgressService): EgressServiceForm => {
  const inject = service.inject || {}
  const authType =
    inject.type === 'cookie'
      ? 'cookie'
      : inject.type === 'api_key' || inject.type === 'raw_header'
        ? 'api_key'
        : 'bearer'
  return {
    name: service.name || '',
    baseUrl: service.base_url || '',
    credentialRef: service.credential_ref || '',
    authType,
    secretKey:
      inject.secret_key ||
      (authType === 'cookie'
        ? 'COOKIE_HEADER'
        : authType === 'bearer'
          ? 'ACCESS_TOKEN'
          : 'API_KEY'),
    header: inject.header || '',
    allowedPaths: (service.allowed_paths || []).join('\n'),
  }
}

export const buildEgressServices = (forms: EgressServiceForm[]): EnvironmentEgressService[] =>
  forms
    .map((service) => {
      const name = service.name.trim()
      const baseUrl = service.baseUrl.trim()
      const credentialRef = service.credentialRef.trim()
      if (!name || !baseUrl || !credentialRef) return null

      const inject: NonNullable<EnvironmentEgressService['inject']> = { type: service.authType }
      if (service.authType === 'bearer') {
        inject.secret_key = service.secretKey.trim() || 'ACCESS_TOKEN'
      } else if (service.authType === 'api_key') {
        inject.secret_key = service.secretKey.trim() || 'API_KEY'
        inject.header = service.header.trim() || 'x-api-key'
      } else {
        inject.secret_key = service.secretKey.trim() || 'COOKIE_HEADER'
      }

      const result: EnvironmentEgressService = {
        name,
        kind: 'external',
        exposure: 'placeholder',
        base_url: baseUrl,
        credential_ref: credentialRef,
        inject,
      }
      const allowedPaths = service.allowedPaths
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
      if (allowedPaths.length > 0) {
        result.allowed_paths = allowedPaths
      }
      return result
    })
    .filter((service): service is EnvironmentEgressService => service !== null)

function updateService(
  setServices: Dispatch<SetStateAction<EgressServiceForm[]>>,
  index: number,
  patch: Partial<EgressServiceForm>,
) {
  setServices((items) => items.map((item, i) => (i === index ? { ...item, ...patch } : item)))
}

function RequiredMark() {
  return <span className="ml-1 text-destructive">*</span>
}

export function EgressServicesEditor({
  services,
  setServices,
  secrets = [],
  errors = {},
  onClearFieldError,
  onRemove,
  onDirty,
}: {
  services: EgressServiceForm[]
  setServices: Dispatch<SetStateAction<EgressServiceForm[]>>
  secrets?: Secret[]
  errors?: EgressServiceErrors
  onClearFieldError?: (index: number, field: EgressServiceErrorField) => void
  onRemove?: (index: number) => void
  onDirty?: () => void
}) {
  const { t } = useTranslation()

  // 只列第三方服务（custom）的密钥；大模型引擎密钥不适用于 egress 凭证注入。
  const customSecrets = secrets.filter((secret) => isCustomSecretProvider(secret.provider))

  const changeService = (
    index: number,
    patch: Partial<EgressServiceForm>,
    field?: EgressServiceErrorField,
  ) => {
    if (field) onClearFieldError?.(index, field)
    updateService(setServices, index, patch)
    onDirty?.()
  }

  return (
    <div className="space-y-3">
      {services.map((service, index) => {
        const selectedSecret = customSecrets.find((secret) => secret.name === service.credentialRef)
        const selectedSecretKeys = secretKeysFor(selectedSecret)
        return (
          <div key={index} className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="flex items-center justify-between gap-3 border-b bg-muted/25 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium">
                    {service.name.trim() || t('managed.environments.egressNewService')}
                  </p>
                  <Badge variant="secondary" className="shrink-0 font-normal">
                    {t('managed.environments.egressExposurePlaceholder')}
                  </Badge>
                </div>
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {service.baseUrl.trim() || 'https://crm.example.com/api/'}
                </p>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={() => onRemove?.(index)}>
                {t('managed.environments.removeEgressService')}
              </Button>
            </div>

            <div className="space-y-4 p-4">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    {t('managed.environments.egressName')}
                    <RequiredMark />
                  </Label>
                  <Input
                    placeholder="crm"
                    value={service.name}
                    aria-invalid={Boolean(errors[index]?.name)}
                    onChange={(event) => changeService(index, { name: event.target.value }, 'name')}
                  />
                  {errors[index]?.name && (
                    <p className="text-xs text-destructive">{errors[index]?.name}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    {t('managed.environments.egressCredential')}
                    <RequiredMark />
                    <FieldHelp text={t('managed.environments.egressCredentialTooltip')} />
                  </Label>
                  {customSecrets.length > 0 ? (
                    <Select
                      value={service.credentialRef}
                      onValueChange={(value) => {
                        const secret = customSecrets.find((item) => item.name === value)
                        changeService(
                          index,
                          {
                            credentialRef: value,
                            secretKey: preferredSecretKey(secretKeysFor(secret), service.authType),
                          },
                          'credentialRef',
                        )
                      }}
                    >
                      <SelectTrigger aria-invalid={Boolean(errors[index]?.credentialRef)}>
                        <SelectValue
                          placeholder={t('managed.environments.egressSelectCredential')}
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {customSecrets.map((secret) => (
                          <SelectItem key={secret.id} value={secret.name}>
                            {secret.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      placeholder="crm-prod"
                      value={service.credentialRef}
                      aria-invalid={Boolean(errors[index]?.credentialRef)}
                      onChange={(event) =>
                        changeService(index, { credentialRef: event.target.value }, 'credentialRef')
                      }
                    />
                  )}
                  {errors[index]?.credentialRef && (
                    <p className="text-xs text-destructive">{errors[index]?.credentialRef}</p>
                  )}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">
                  {t('managed.environments.egressBaseUrl')}
                  <RequiredMark />
                </Label>
                <Input
                  placeholder="https://crm.example.com/api/"
                  value={service.baseUrl}
                  aria-invalid={Boolean(errors[index]?.baseUrl)}
                  onChange={(event) =>
                    changeService(index, { baseUrl: event.target.value }, 'baseUrl')
                  }
                />
                {errors[index]?.baseUrl && (
                  <p className="text-xs text-destructive">{errors[index]?.baseUrl}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">
                  {t('managed.environments.egressAllowedPaths')}
                  <span className="ml-1 font-normal text-muted-foreground/70">
                    {t('managed.environments.egressOptional')}
                  </span>
                  <FieldHelp text={t('managed.environments.egressAllowedPathsHint')} />
                </Label>
                <Textarea
                  rows={3}
                  className="font-mono text-xs"
                  placeholder={t('managed.environments.egressAllowedPathsPlaceholder')}
                  value={service.allowedPaths}
                  onChange={(event) =>
                    changeService(index, { allowedPaths: event.target.value })
                  }
                />
              </div>

              <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
                <p className="text-xs text-muted-foreground">
                  {t('managed.environments.egressAuthHint')}
                </p>
                <div
                  className={`grid gap-3 ${
                    service.authType === 'api_key' ? 'md:grid-cols-3' : 'md:grid-cols-2'
                  }`}
                >
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      {t('managed.environments.egressAuthType')}
                      <RequiredMark />
                    </Label>
                    <Select
                      value={service.authType}
                      onValueChange={(value) => {
                        const authType = value as EgressServiceForm['authType']
                        changeService(index, {
                          ...defaultsForAuthType(authType),
                          secretKey: preferredSecretKey(selectedSecretKeys, authType),
                        })
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="bearer">Bearer Token</SelectItem>
                        <SelectItem value="api_key">API Key</SelectItem>
                        <SelectItem value="cookie">Cookie</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {service.authType === 'api_key' && (
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">
                        {t('managed.environments.egressHeader')}
                      </Label>
                      <Input
                        placeholder="x-api-key"
                        value={service.header}
                        onChange={(event) => changeService(index, { header: event.target.value })}
                      />
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      {t('managed.environments.egressSecretKey')}
                      {service.authType === 'cookie' && <RequiredMark />}
                      <FieldHelp
                        text={
                          service.authType === 'cookie'
                            ? t('managed.environments.egressCookieSecretKeyTooltip')
                            : t('managed.environments.egressSecretKeyTooltip')
                        }
                      />
                      {service.authType !== 'cookie' && (
                        <span className="ml-1 font-normal text-muted-foreground/70">
                          {t('managed.environments.egressOptional')}
                        </span>
                      )}
                    </Label>
                    {selectedSecretKeys.length > 0 ? (
                      <Select
                        value={service.secretKey}
                        onValueChange={(value) =>
                          changeService(index, { secretKey: value }, 'secretKey')
                        }
                      >
                        <SelectTrigger aria-invalid={Boolean(errors[index]?.secretKey)}>
                          <SelectValue
                            placeholder={t('managed.environments.egressSelectSecretKey')}
                          />
                        </SelectTrigger>
                        <SelectContent>
                          {selectedSecretKeys.map((key) => (
                            <SelectItem key={key} value={key}>
                              {key}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        placeholder={
                          service.authType === 'cookie'
                            ? 'COOKIE_HEADER'
                            : service.authType === 'api_key'
                              ? 'API_KEY'
                              : 'ACCESS_TOKEN'
                        }
                        value={service.secretKey}
                        aria-invalid={Boolean(errors[index]?.secretKey)}
                        onChange={(event) =>
                          changeService(index, { secretKey: event.target.value }, 'secretKey')
                        }
                      />
                    )}
                    {errors[index]?.secretKey && (
                      <p className="text-xs text-destructive">{errors[index]?.secretKey}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-2 rounded-lg border border-dashed bg-background p-3 text-xs">
                <div>
                  <p className="mb-1 font-medium text-muted-foreground">
                    {t('managed.environments.egressSkillExample')}
                  </p>
                  <code className="block truncate rounded bg-muted px-2 py-1 text-foreground">
                    {egressHttpDirectUrl(service.baseUrl)}
                  </code>
                </div>
                <div>
                  <p className="mb-1 font-medium text-muted-foreground">
                    {t('managed.environments.egressInjectExample')}
                  </p>
                  <code className="block truncate rounded bg-muted px-2 py-1 text-foreground">
                    {egressInjectedHeaderExample(service)}
                  </code>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
