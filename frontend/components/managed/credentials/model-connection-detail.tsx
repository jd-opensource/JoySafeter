'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Save } from 'lucide-react'
import { useMemo, useState } from 'react'

import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import { FormFieldLabel, MonoId, PageHeader, RelativeTime } from '@/components/managed/shared'
import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { findCredentialProfileForBinding } from '@/lib/managed/llm-catalog'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { LlmCredentialField } from '@/types/llm'
import type { SecretDetail } from '@/types/managed'

function inputType(field: LlmCredentialField, showValues: boolean) {
  if (field.type === 'secret' && !showValues) return 'password'
  if (field.type === 'url') return 'url'
  return 'text'
}

export function ModelConnectionDetail({ credential }: { credential: SecretDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [values, setValues] = useState<Record<string, string>>(credential.data)
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const profile = useMemo(() => {
    if (!catalogQuery.data || !credential.provider || !credential.protocol) return null
    return findCredentialProfileForBinding(
      catalogQuery.data,
      credential.provider,
      credential.protocol,
    )
  }, [catalogQuery.data, credential.provider, credential.protocol])
  const catalogIdentityUnavailable = catalogQuery.isSuccess && !profile

  const save = async () => {
    if (projectReadOnly) return
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data: values },
        managedRequestOptions(managedScope),
      )
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(['credential-detail', managedScope.key, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
      queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
      setValues(updated.data)
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
  if (!catalogReady) return <LlmCatalogPageState state="loading" />

  return (
    <div className="space-y-6">
      <PageHeader
        title={credential.name}
        breadcrumb={[
          { label: t('managed.credentials.tabs.models'), to: '/managed/credentials?tab=models' },
          { label: credential.name },
        ]}
        titleExtra={<Badge variant="default">{t('managed.llm.modelConfiguration')}</Badge>}
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
          <MonoId id={credential.id} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.provider')}</p>
          <p className="mt-1 text-sm font-medium">{credential.provider ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.protocol')}</p>
          <p className="mt-1 text-sm font-medium">{credential.protocol ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.updated')}</p>
          <p className="mt-1 text-sm">
            <RelativeTime date={credential.updated_at} />
          </p>
        </div>
        <div className="sm:col-span-2 lg:col-span-4">
          <p className="mb-2 text-xs text-muted-foreground">
            {t('managed.llm.compatibleEngines')}
          </p>
          <CompatibleEngineBadges
            engineIds={credential.compatible_engine_ids}
            catalog={catalogQuery.data}
          />
        </div>
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('managed.secrets.dataLabel')}</h2>
            <p className="text-xs text-muted-foreground">
              {t('managed.llm.identityImmutableHint')}
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>
        {profile ? (
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
                    onChange={(e) => {
                      setValues((c) => ({ ...c, [field.key]: e.target.value }))
                      setDirty(true)
                    }}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">{t('common.select')}</option>
                    {field.options.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id={`secret-${field.key}`}
                    type={inputType(field, showValues)}
                    value={values[field.key] ?? ''}
                    disabled={projectReadOnly}
                    onChange={(e) => {
                      setValues((c) => ({ ...c, [field.key]: e.target.value }))
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
        )}
      </section>
    </div>
  )
}
