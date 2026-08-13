'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Plus, Save, Trash2 } from 'lucide-react'
import React, { useEffect, useMemo, useState } from 'react'

import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import {
  FormFieldLabel,
  MonoId,
  PageHeader,
  RelativeTime,
  ResourceErrorState,
  withEntityRouteGuard,
} from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { managedGet, managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { findCredentialProfileForBinding } from '@/lib/managed/llm-catalog'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import { isSecretValueMaskedKey } from '@/lib/managed/secret-keys'
import { secretDetailQueryKey } from '@/lib/managed/secret-query-keys'
import { parseCredentialId } from '@/types/entity-id'
import type { LlmCredentialField } from '@/types/llm'
import type { SecretDetail } from '@/types/managed'

interface GenericPair {
  key: string
  value: string
}

function inputType(field: LlmCredentialField, showValues: boolean) {
  if (field.type === 'secret' && !showValues) return 'password'
  if (field.type === 'url') return 'url'
  return 'text'
}

export default withEntityRouteGuard(SecretDetailPageInner, {
  kind: 'secret',
  idKind: 'credential',
  paramKey: 'secretId',
  backTo: '/managed/secrets',
})

function SecretDetailPageInner({ params }: { params: Promise<{ secretId: string }> }) {
  const { secretId: rawSecretId } = React.use(params)
  const secretId = parseCredentialId(rawSecretId)
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [values, setValues] = useState<Record<string, string>>({})
  const [genericPairs, setGenericPairs] = useState<GenericPair[]>([])
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const secretQuery = useQuery({
    queryKey: secretDetailQueryKey(managedScope.key, secretId, catalogVersion),
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('credentials', secretId),
        managedRequestOptions(managedScope),
      ).then(parseSecretDetailResponse),
    enabled: catalogReady && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })

  useEffect(() => {
    if (!secretQuery.data || dirty) return
    setValues(secretQuery.data.data)
    setGenericPairs(
      Object.entries(secretQuery.data.data).map(([key, value]) => ({ key, value })),
    )
  }, [dirty, secretQuery.data])

  const profile = useMemo(() => {
    const secret = secretQuery.data
    if (
      !catalogQuery.data ||
      !secret ||
      secret.kind !== 'model' ||
      !secret.provider ||
      !secret.protocol
    ) {
      return null
    }
    return findCredentialProfileForBinding(catalogQuery.data, secret.provider, secret.protocol)
  }, [catalogQuery.data, secretQuery.data])
  const catalogIdentityUnavailable =
    secretQuery.data?.kind === 'model' && catalogQuery.isSuccess && !profile

  const save = async () => {
    const secret = secretQuery.data
    if (!secret || projectReadOnly) return
    const data =
      secret.kind === 'model'
        ? values
        : Object.fromEntries(
            genericPairs
              .map((pair) => [pair.key.trim(), pair.value] as const)
              .filter(([key]) => Boolean(key)),
          )
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', secret.id),
        { data },
        managedRequestOptions(managedScope),
      )
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(
        secretDetailQueryKey(managedScope.key, secret.id, catalogVersion),
        updated,
      )
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
      queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
      setValues(updated.data)
      setGenericPairs(Object.entries(updated.data).map(([key, value]) => ({ key, value })))
      setDirty(false)
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setSaving(false)
    }
  }

  if (catalogQuery.isError) {
    return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  }
  if (!catalogReady) {
    return <LlmCatalogPageState state="loading" />
  }
  if (secretQuery.isError) {
    return (
      <ResourceErrorState
        error={secretQuery.error}
        resource="secret"
        onRetry={() => secretQuery.refetch()}
      />
    )
  }
  if (secretQuery.isLoading || !secretQuery.data) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">{t('common.loading')}</div>
    )
  }

  const secret: SecretDetail = secretQuery.data
  return (
    <div className="space-y-6">
      <PageHeader
        title={secret.name}
        breadcrumb={[
          { label: t('managed.secrets.title'), to: '/managed/secrets' },
          { label: secret.name },
        ]}
        titleExtra={
          <Badge variant={secret.kind === 'model' ? 'default' : 'outline'}>
            {secret.kind === 'model'
              ? t('managed.llm.modelConfiguration')
              : t('managed.llm.genericSecret')}
          </Badge>
        }
        action={
          projectReadOnly ? null : (
            <Button onClick={save} disabled={!dirty || saving || catalogIdentityUnavailable}>
              <Save className="mr-1 h-4 w-4" />
              {saving ? t('common.loading') : t('common.save')}
            </Button>
          )
        }
      />

      <section className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.id')}</p>
          <MonoId id={secret.id} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.provider')}</p>
          <p className="mt-1 text-sm font-medium">{secret.provider ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.protocol')}</p>
          <p className="mt-1 text-sm font-medium">{secret.protocol ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.updated')}</p>
          <p className="mt-1 text-sm">
            <RelativeTime date={secret.updated_at} />
          </p>
        </div>
        {secret.kind === 'model' ? (
          <div className="sm:col-span-2 lg:col-span-4">
            <p className="mb-2 text-xs text-muted-foreground">
              {t('managed.llm.compatibleEngines')}
            </p>
            <CompatibleEngineBadges
              engineIds={secret.compatible_engine_ids}
              catalog={catalogQuery.data}
            />
          </div>
        ) : null}
      </section>

      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('managed.secrets.dataLabel')}</h2>
            {secret.kind === 'model' ? (
              <p className="text-xs text-muted-foreground">
                {t('managed.llm.identityImmutableHint')}
              </p>
            ) : null}
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>

        {secret.kind === 'model' ? (
          profile ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {profile.fields.map((field) => (
                <div key={field.key} className="space-y-2">
                  <FormFieldLabel htmlFor={`secret-${field.key}`} required={field.required}>
                    {field.label}
                  </FormFieldLabel>
                  {field.type === 'select' ? (
                    <select
                      id={`secret-${field.key}`}
                      value={values[field.key] ?? ''}
                      disabled={projectReadOnly}
                      onChange={(event) => {
                        setValues((current) => ({ ...current, [field.key]: event.target.value }))
                        setDirty(true)
                      }}
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
                      id={`secret-${field.key}`}
                      type={inputType(field, showValues)}
                      value={values[field.key] ?? ''}
                      disabled={projectReadOnly}
                      onChange={(event) => {
                        setValues((current) => ({ ...current, [field.key]: event.target.value }))
                        setDirty(true)
                      }}
                    />
                  )}
                  <code className="block text-[11px] text-muted-foreground">{field.key}</code>
                </div>
              ))}
            </div>
          ) : (
            <Alert variant="destructive">
              <AlertDescription>{t('managed.llm.catalogIdentityUnavailable')}</AlertDescription>
            </Alert>
          )
        ) : (
          <div className="space-y-3">
            {genericPairs.map((pair, index) => (
              <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Input
                  value={pair.key}
                  disabled={projectReadOnly}
                  onChange={(event) => {
                    setGenericPairs((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, key: event.target.value } : item,
                      ),
                    )
                    setDirty(true)
                  }}
                />
                <Input
                  type={isSecretValueMaskedKey(pair.key) && !showValues ? 'password' : 'text'}
                  value={pair.value}
                  disabled={projectReadOnly}
                  onChange={(event) => {
                    setGenericPairs((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, value: event.target.value } : item,
                      ),
                    )
                    setDirty(true)
                  }}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={projectReadOnly}
                  onClick={() => {
                    setGenericPairs((current) =>
                      current.filter((_, itemIndex) => itemIndex !== index),
                    )
                    setDirty(true)
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {!projectReadOnly ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setGenericPairs((current) => [...current, { key: '', value: '' }])
                  setDirty(true)
                }}
              >
                <Plus className="mr-1 h-4 w-4" />
                {t('managed.secrets.addPair')}
              </Button>
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
