'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, Eye, EyeOff, RotateCcw, Save, Star, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useRef, useState } from 'react'

import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import {
  ConfirmDialog,
  FormFieldLabel,
  MonoId,
  PageHeader,
  RelativeTime,
  StatusBadge,
} from '@/components/managed/shared'
import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { compatibleCredentialsScopePrefix } from '@/hooks/managed/use-compatible-credentials'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPatch, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { findCredentialProfileForBinding } from '@/lib/managed/llm-catalog'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { parseCredentialDetailResponse } from '@/lib/managed/credential-response-parsers'
import type { LlmCredentialField } from '@/types/llm'
import type { CredentialDetail } from '@/types/managed'

function inputType(field: LlmCredentialField, showValues: boolean) {
  if (field.type === 'secret' && !showValues) return 'password'
  if (field.type === 'url') return 'url'
  return 'text'
}

export function ModelConnectionDetail({ credential }: { credential: CredentialDetail }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const sourceDataRef = useRef(credential.data)
  const [values, setValues] = useState<Record<string, string>>(credential.data)
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmAction, setConfirmAction] = useState<'archive' | 'restore' | 'delete' | null>(null)
  const [lifecyclePending, setLifecyclePending] = useState(false)
  const {
    readOnly: projectReadOnly,
    beginAction,
    isCurrentAction,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      setDirty(false)
      setShowValues(false)
      setSaving(false)
      setLifecyclePending(false)
      setConfirmAction(null)
    },
  })
  const credentialReadOnly = projectReadOnly || Boolean(credential.archived_at)
  const mutationPending = saving || lifecyclePending
  const formReadOnly = credentialReadOnly || mutationPending

  if (!dirty && sourceDataRef.current !== credential.data) {
    sourceDataRef.current = credential.data
    setValues(credential.data)
  }

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
    if (credentialReadOnly || mutationPending) return
    const action = beginAction()
    if (!action) return
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data: values },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      const updated = parseCredentialDetailResponse(response)
      queryClient.setQueryData(['credential-detail', action.scope, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', action.scope] })
      queryClient.invalidateQueries({ queryKey: compatibleCredentialsScopePrefix(action.scope) })
      sourceDataRef.current = updated.data
      setValues(updated.data)
      setDirty(false)
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setSaving(false)
    }
  }

  const invalidate = (scope: string) => {
    queryClient.invalidateQueries({ queryKey: ['credential-detail', scope, credential.id] })
    queryClient.invalidateQueries({ queryKey: ['credentials', scope] })
    queryClient.invalidateQueries({ queryKey: compatibleCredentialsScopePrefix(scope) })
  }

  const setDefault = async () => {
    if (credentialReadOnly || credential.is_default || mutationPending) return
    const action = beginAction()
    if (!action) return
    setLifecyclePending(true)
    try {
      await managedPost(
        apiResourcePath('credentials', credential.id, 'default'),
        {},
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      invalidate(action.scope)
    } catch (error) {
      if (!isCurrentAction(action.runId, action.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setLifecyclePending(false)
    }
  }

  const confirmLifecycle = async () => {
    if (!confirmAction || projectReadOnly || mutationPending) return
    if (confirmAction === 'archive' && credential.archived_at) return
    if (confirmAction === 'restore' && !credential.archived_at) return
    const action = confirmAction
    const scopedAction = beginAction()
    if (!scopedAction) {
      setConfirmAction(null)
      return
    }
    setLifecyclePending(true)
    try {
      if (action === 'delete') {
        await managedDelete(
          apiResourcePath('credentials', credential.id),
          managedRequestOptions(scopedAction.requestScope),
        )
        if (!isCurrentAction(scopedAction.runId, scopedAction.scope)) return
        queryClient.removeQueries({
          queryKey: ['credential-detail', scopedAction.scope, credential.id],
        })
        queryClient.invalidateQueries({ queryKey: ['credentials', scopedAction.scope] })
        queryClient.invalidateQueries({
          queryKey: compatibleCredentialsScopePrefix(scopedAction.scope),
        })
        router.push('/managed/credentials?tab=models')
      } else {
        await managedPost(
          apiResourcePath('credentials', credential.id, action),
          {},
          managedRequestOptions(scopedAction.requestScope),
        )
        if (!isCurrentAction(scopedAction.runId, scopedAction.scope)) return
        invalidate(scopedAction.scope)
      }
    } catch (error) {
      if (!isCurrentAction(scopedAction.runId, scopedAction.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      if (isCurrentAction(scopedAction.runId, scopedAction.scope)) {
        setLifecyclePending(false)
        setConfirmAction(null)
      }
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
        titleExtra={
          <div className="flex items-center gap-2">
            <Badge variant="default">{t('managed.llm.modelConfiguration')}</Badge>
            <StatusBadge status={credential.archived_at ? 'archived' : 'active'} />
          </div>
        }
        action={
          projectReadOnly ? null : (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {!credential.archived_at ? (
                <>
                  <Button
                    onClick={save}
                    disabled={!dirty || mutationPending || catalogIdentityUnavailable}
                  >
                    <Save className="mr-1 h-4 w-4" />
                    {saving ? t('common.loading') : t('common.save')}
                  </Button>
                  {!credential.is_default ? (
                    <Button variant="outline" onClick={setDefault} disabled={mutationPending}>
                      <Star className="mr-1 h-4 w-4" />
                      {t('managed.llm.setAsProtocolDefault')}
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    onClick={() => setConfirmAction('archive')}
                    disabled={mutationPending}
                  >
                    <Archive className="mr-1 h-4 w-4" />
                    {t('common.archive')}
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  onClick={() => setConfirmAction('restore')}
                  disabled={mutationPending}
                >
                  <RotateCcw className="mr-1 h-4 w-4" />
                  {t('common.restore')}
                </Button>
              )}
              <Button
                variant="outline"
                onClick={() => setConfirmAction('delete')}
                disabled={mutationPending}
              >
                <Trash2 className="mr-1 h-4 w-4" />
                {t('common.delete')}
              </Button>
            </div>
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
          <p className="mb-2 text-xs text-muted-foreground">{t('managed.llm.compatibleEngines')}</p>
          <CompatibleEngineBadges
            engineIds={credential.compatible_engine_ids}
            catalog={catalogQuery.data}
          />
        </div>
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('managed.credentials.resources.dataLabel')}</h2>
            <p className="text-xs text-muted-foreground">
              {t('managed.llm.identityImmutableHint')}
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues
              ? t('managed.credentials.resources.hideValues')
              : t('managed.credentials.resources.showValues')}
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
                    disabled={formReadOnly}
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
                    disabled={formReadOnly}
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
      <ConfirmDialog
        open={Boolean(confirmAction)}
        title={t(
          confirmAction === 'delete'
            ? 'managed.credentials.resources.deleteTitle'
            : confirmAction === 'restore'
              ? 'managed.credentials.resources.restoreTitle'
              : 'managed.credentials.resources.archiveTitle',
        )}
        description={t(
          confirmAction === 'delete'
            ? 'managed.credentials.resources.deleteDescription'
            : confirmAction === 'restore'
              ? 'managed.credentials.resources.restoreDescription'
              : 'managed.credentials.resources.archiveDescription',
          { name: credential.name },
        )}
        confirmLabel={t(
          confirmAction === 'delete'
            ? 'common.delete'
            : confirmAction === 'restore'
              ? 'common.restore'
              : 'common.archive',
        )}
        destructive={confirmAction === 'delete'}
        onConfirm={confirmLifecycle}
        onCancel={() => {
          bumpRun()
          setConfirmAction(null)
        }}
      />
    </div>
  )
}
