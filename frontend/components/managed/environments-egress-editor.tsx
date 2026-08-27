'use client'

import { ChevronDown, ChevronRight, Plus, Search, Trash2, X } from 'lucide-react'
import { useMemo, useState, type Dispatch, type SetStateAction } from 'react'

import { CopyButton as SharedCopyButton } from '@/components/managed/shared/copy-button'
import { FieldHelp } from '@/components/managed/shared/field-help'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import { filterSelectableCredentials } from '@/lib/managed/credential-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Credential, EnvironmentEgressService } from '@/types/managed'

// Sentinel value for the "create secret" option in the credential dropdown.
const CREATE_SECRET_OPTION = '__create_secret__'

export type EgressServiceForm = {
  name: string
  baseUrl: string
  authSource: 'service_credential' | 'agent_identity'
  credentialRef: string
  authType: 'bearer' | 'api_key' | 'cookie'
  secretKey: string
  header: string
  allowedPaths: string
}

export type EgressServiceErrorField =
  | 'name'
  | 'baseUrl'
  | 'credentialRef'
  | 'secretKey'
  | 'allowedPaths'
export type EgressServiceErrors = Record<number, Partial<Record<EgressServiceErrorField, string>>>

export const emptyEgressService = (): EgressServiceForm => ({
  name: '',
  baseUrl: '',
  authSource: 'service_credential',
  credentialRef: '',
  authType: 'bearer',
  secretKey: '',
  header: '',
  allowedPaths: '',
})

const egressInjectedHeaderExample = (service: EgressServiceForm, agentIdentityLabel: string) => {
  if (service.authSource === 'agent_identity') return agentIdentityLabel
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

// Skill 始终通过 Envoy 的 HTTP 入口访问；Envoy 再按配置的 HTTP/HTTPS 协议回源。
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

const secretKeysFor = (secret?: Credential) => Object.keys(secret?.data || {})

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
    authSource: service.auth_source === 'agent_identity' ? 'agent_identity' : 'service_credential',
    credentialRef: service.credential_ref || '',
    authType,
    secretKey:
      inject.credential_field ||
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
  forms.flatMap((service): EnvironmentEgressService[] => {
    const name = service.name.trim()
    const baseUrl = service.baseUrl.trim()
    const credentialRef = service.credentialRef.trim()
    if (!name || !baseUrl) return []

    const allowedPaths = service.allowedPaths
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    if (service.authSource === 'agent_identity') {
      return [
        {
          name,
          kind: 'external',
          exposure: 'placeholder',
          base_url: baseUrl,
          auth_source: 'agent_identity',
          allowed_paths: allowedPaths.length > 0 ? allowedPaths : ['/'],
        },
      ]
    }
    if (!credentialRef) return []

    const inject: NonNullable<EnvironmentEgressService['inject']> = { type: service.authType }
    if (service.authType === 'bearer') {
      inject.credential_field = service.secretKey.trim() || 'ACCESS_TOKEN'
    } else if (service.authType === 'api_key') {
      inject.credential_field = service.secretKey.trim() || 'API_KEY'
      inject.header = service.header.trim() || 'x-api-key'
    } else {
      inject.credential_field = service.secretKey.trim() || 'COOKIE_HEADER'
    }

    const result: EnvironmentEgressService = {
      name,
      kind: 'external',
      exposure: 'placeholder',
      base_url: baseUrl,
      auth_source: 'service_credential',
      credential_ref: parseCredentialId(credentialRef),
      inject,
    }
    if (allowedPaths.length > 0) {
      result.allowed_paths = allowedPaths
    }
    return [result]
  })

export function validateEgressServiceForms(
  services: EgressServiceForm[],
  messages: { required: string; cookieRequired: string },
): EgressServiceErrors {
  const errors: EgressServiceErrors = {}
  services.forEach((service, index) => {
    const serviceErrors: Partial<Record<EgressServiceErrorField, string>> = {}
    if (!service.name.trim()) serviceErrors.name = messages.required
    if (!service.baseUrl.trim()) serviceErrors.baseUrl = messages.required
    if (service.authSource === 'service_credential' && !service.credentialRef.trim()) {
      serviceErrors.credentialRef = messages.required
    }
    if (
      service.authSource === 'service_credential' &&
      service.authType === 'cookie' &&
      !service.secretKey.trim()
    ) {
      serviceErrors.secretKey = messages.cookieRequired
    }
    if (Object.keys(serviceErrors).length > 0) errors[index] = serviceErrors
  })
  return errors
}

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

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-3.5 w-1 rounded-full bg-primary" />
      <p className="text-sm font-semibold text-foreground">{children}</p>
    </div>
  )
}

function CopyButton({ value }: { value: string }) {
  return <SharedCopyButton value={value} />
}

function SearchableSecretSelect({
  value,
  secrets,
  placeholder,
  searchPlaceholder,
  emptyText,
  createText,
  invalid,
  onChange,
  onCreate,
}: {
  value: string
  secrets: Credential[]
  placeholder: string
  searchPlaceholder: string
  emptyText: string
  createText: string
  invalid?: boolean
  onChange: (value: string) => void
  onCreate: () => void
}) {
  const [search, setSearch] = useState('')
  const filteredSecrets = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return secrets
    return secrets.filter((secret) =>
      `${secret.name} ${secret.provider || ''} ${secret.protocol || ''}`
        .toLowerCase()
        .includes(query),
    )
  }, [secrets, search])

  return (
    <Select
      value={value || undefined}
      onValueChange={(nextValue) => {
        if (nextValue === CREATE_SECRET_OPTION) {
          onCreate()
          return
        }
        onChange(nextValue)
      }}
    >
      <SelectTrigger aria-invalid={invalid}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-80">
        <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={searchPlaceholder}
              className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch('')}
                onMouseDown={(event) => event.preventDefault()}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>
        {filteredSecrets.length > 0 ? (
          filteredSecrets.map((secret) => (
            <SelectItem key={secret.id} value={secret.id}>
              {secret.name}
            </SelectItem>
          ))
        ) : (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">{emptyText}</div>
        )}
        <SelectItem value={CREATE_SECRET_OPTION} className="text-primary">
          <span className="flex items-center gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            {createText}
          </span>
        </SelectItem>
      </SelectContent>
    </Select>
  )
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
  secrets?: Credential[]
  errors?: EgressServiceErrors
  onClearFieldError?: (index: number, field: EgressServiceErrorField) => void
  onRemove?: (index: number) => void
  onDirty?: () => void
}) {
  const { t } = useTranslation()

  // 折叠状态：记录被折叠的服务索引（默认全部展开）。
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const toggleCollapsed = (index: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const customSecrets = filterSelectableCredentials(
    secrets.filter((secret) => secret.kind === 'service'),
  )

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
        const selectedCredential = customSecrets.find(
          (secret) => secret.id === service.credentialRef,
        )
        const selectedCredentialFields = secretKeysFor(selectedCredential)
        const isCollapsed = collapsed.has(index)
        return (
          <div key={index} className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="flex items-center gap-2 border-b bg-muted/25 px-3 py-2.5">
              <button
                type="button"
                onClick={() => toggleCollapsed(index)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                <span className="shrink-0 text-sm font-medium">
                  {service.name.trim() || t('managed.environments.egressNewService')}
                </span>
                {service.baseUrl.trim() && (
                  <span className="min-w-0 truncate text-xs text-muted-foreground">
                    {service.baseUrl.trim()}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => onRemove?.(index)}
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                aria-label={t('managed.environments.removeEgressService')}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {!isCollapsed && (
              <div className="space-y-5 p-4">
                {/* ── 基本信息 ── */}
                <div className="space-y-3">
                  <SectionTitle>{t('managed.environments.egressSectionBasic')}</SectionTitle>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      {t('managed.environments.egressName')}
                      <RequiredMark />
                    </Label>
                    <Input
                      placeholder="crm"
                      value={service.name}
                      aria-invalid={Boolean(errors[index]?.name)}
                      onChange={(event) =>
                        changeService(index, { name: event.target.value }, 'name')
                      }
                    />
                    {errors[index]?.name && (
                      <p className="text-xs text-destructive">{errors[index]?.name}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      {t('managed.environments.egressBaseUrl')}
                      <RequiredMark />
                      <FieldHelp text={t('managed.environments.egressBaseUrlHint')} />
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
                </div>

                {/* ── 身份认证 ── */}
                <div className="space-y-3 border-t pt-4">
                  <SectionTitle>{t('managed.environments.egressSectionCredential')}</SectionTitle>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      {t('managed.environments.egressAuthSource')}
                      <RequiredMark />
                    </Label>
                    <Select
                      value={service.authSource}
                      onValueChange={(value) =>
                        changeService(index, {
                          authSource: value as EgressServiceForm['authSource'],
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="service_credential">
                          {t('managed.environments.egressAuthSourceStatic')}
                        </SelectItem>
                        <SelectItem value="agent_identity">
                          {t('managed.environments.egressAuthSourceAgentIdentity')}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {service.authSource === 'agent_identity'
                        ? t('managed.environments.egressAgentIdentityHint')
                        : t('managed.environments.egressStaticCredentialHint')}
                    </p>
                  </div>

                  {service.authSource === 'service_credential' && (
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">
                        {t('managed.environments.egressCredential')}
                        <RequiredMark />
                        <FieldHelp text={t('managed.environments.egressCredentialTooltip')} />
                      </Label>
                      <SearchableSecretSelect
                        value={service.credentialRef}
                        secrets={customSecrets}
                        placeholder={t('managed.environments.egressSelectCredential')}
                        searchPlaceholder={t('managed.environments.egressSearchCredential')}
                        emptyText={t('managed.environments.egressNoCredentialFound')}
                        createText={t('managed.environments.egressCreateServiceCredentialOption')}
                        invalid={Boolean(errors[index]?.credentialRef)}
                        onCreate={() =>
                          window.open('/managed/credentials?tab=services&create=service', '_blank')
                        }
                        onChange={(value) => {
                          const credential = customSecrets.find((item) => item.id === value)
                          changeService(
                            index,
                            {
                              credentialRef: value,
                              secretKey: preferredSecretKey(
                                secretKeysFor(credential),
                                service.authType,
                              ),
                            },
                            'credentialRef',
                          )
                        }}
                      />
                      {errors[index]?.credentialRef && (
                        <p className="text-xs text-destructive">{errors[index]?.credentialRef}</p>
                      )}
                    </div>
                  )}

                  {service.authSource === 'service_credential' && (
                    <p className="text-xs text-muted-foreground">
                      {t('managed.environments.egressAuthHint')}
                    </p>
                  )}
                  {service.authSource === 'service_credential' && (
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
                              secretKey: preferredSecretKey(selectedCredentialFields, authType),
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
                            onChange={(event) =>
                              changeService(index, { header: event.target.value })
                            }
                          />
                        </div>
                      )}

                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">
                          {t('managed.environments.egressCredentialField')}
                          {service.authType === 'cookie' && <RequiredMark />}
                          <FieldHelp
                            text={
                              service.authType === 'cookie'
                                ? t('managed.environments.egressCookieCredentialFieldTooltip')
                                : t('managed.environments.egressCredentialFieldTooltip')
                            }
                          />
                          {service.authType !== 'cookie' && (
                            <span className="ml-1 font-normal text-muted-foreground/70">
                              {t('managed.environments.egressOptional')}
                            </span>
                          )}
                        </Label>
                        {selectedCredentialFields.length > 0 ? (
                          <Select
                            value={service.secretKey}
                            onValueChange={(value) =>
                              changeService(index, { secretKey: value }, 'secretKey')
                            }
                          >
                            <SelectTrigger aria-invalid={Boolean(errors[index]?.secretKey)}>
                              <SelectValue
                                placeholder={t('managed.environments.egressSelectCredentialField')}
                              />
                            </SelectTrigger>
                            <SelectContent>
                              {selectedCredentialFields.map((key) => (
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
                  )}
                </div>

                {/* ── 访问控制 ── */}
                <div className="space-y-3 border-t pt-4">
                  <SectionTitle>{t('managed.environments.egressSectionAccess')}</SectionTitle>
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
                      aria-invalid={Boolean(errors[index]?.allowedPaths)}
                      onChange={(event) =>
                        changeService(index, { allowedPaths: event.target.value }, 'allowedPaths')
                      }
                    />
                    {errors[index]?.allowedPaths && (
                      <p className="text-xs text-destructive">{errors[index]?.allowedPaths}</p>
                    )}
                  </div>
                </div>

                {/* ── 预览 ── */}
                <div className="space-y-2 border-t pt-4 text-xs">
                  <SectionTitle>{t('managed.environments.egressSectionPreview')}</SectionTitle>
                  <div>
                    <p className="mb-1 font-medium text-muted-foreground">
                      {t('managed.environments.egressSkillExample')}
                    </p>
                    <div className="flex items-center gap-1">
                      <code className="block flex-1 truncate rounded bg-muted px-2 py-1 text-foreground">
                        {egressHttpDirectUrl(service.baseUrl)}
                      </code>
                      <CopyButton value={egressHttpDirectUrl(service.baseUrl)} />
                    </div>
                    <p className="mt-1 text-muted-foreground/70">
                      {t('managed.environments.egressSkillExampleHint')}
                    </p>
                  </div>
                  <div>
                    <p className="mb-1 font-medium text-muted-foreground">
                      {t('managed.environments.egressInjectExample')}
                    </p>
                    <code className="block truncate rounded bg-muted px-2 py-1 text-foreground">
                      {egressInjectedHeaderExample(
                        service,
                        t('managed.environments.egressAuthSourceAgentIdentity'),
                      )}
                    </code>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
