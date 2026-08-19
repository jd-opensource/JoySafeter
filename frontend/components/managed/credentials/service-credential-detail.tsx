'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Archive, Eye, EyeOff, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { CredentialReferences } from '@/components/managed/credentials/credential-references'
import {
  MonoId,
  PageHeader,
  RelativeTime,
  StatusBadge,
} from '@/components/managed/shared'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCredentialReferences } from '@/hooks/managed/use-credential-references'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPatch, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { isSecretValueMaskedKey } from '@/lib/managed/secret-keys'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { SecretDetail } from '@/types/managed'

interface GenericPair {
  key: string
  value: string
}

export function ServiceCredentialDetail({ credential }: { credential: SecretDetail }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const referencesQuery = useCredentialReferences(credential.id)
  const sourceDataRef = useRef(credential.data)
  const [pairs, setPairs] = useState<GenericPair[]>(
    Object.entries(credential.data).map(([key, value]) => ({ key, value })),
  )
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmAction, setConfirmAction] = useState<'archive' | 'restore' | 'delete' | null>(null)
  const [lifecyclePending, setLifecyclePending] = useState(false)
  const confirmedRef = useRef(false)
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

  const blocked =
    confirmAction === 'archive'
      ? referencesQuery.data?.canArchive === false
      : confirmAction === 'delete'
        ? referencesQuery.data?.canDelete === false
        : false

  useEffect(() => {
    if (confirmAction) confirmedRef.current = false
  }, [confirmAction])

  if (!dirty && sourceDataRef.current !== credential.data) {
    sourceDataRef.current = credential.data
    setPairs(Object.entries(credential.data).map(([key, value]) => ({ key, value })))
  }

  const save = async () => {
    if (credentialReadOnly || mutationPending) return
    const action = beginAction()
    if (!action) return
    const data = Object.fromEntries(
      pairs.map((p) => [p.key.trim(), p.value] as const).filter(([k]) => Boolean(k)),
    )
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(['credential-detail', action.scope, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', action.scope] })
      sourceDataRef.current = updated.data
      setPairs(Object.entries(updated.data).map(([key, value]) => ({ key, value })))
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
  }

  const confirmLifecycle = async () => {
    if (!confirmAction || projectReadOnly || mutationPending) return
    if (blocked) return
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
        router.push('/managed/credentials?tab=services')
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

  return (
    <div className="space-y-6">
      <PageHeader
        title={credential.name}
        breadcrumb={[
          {
            label: t('managed.credentials.tabs.services'),
            to: '/managed/credentials?tab=services',
          },
          { label: credential.name },
        ]}
        titleExtra={
          <div className="flex items-center gap-2">
            <Badge variant="outline">{t('managed.llm.genericSecret')}</Badge>
            <StatusBadge status={credential.archived_at ? 'archived' : 'active'} />
          </div>
        }
        action={
          projectReadOnly ? null : (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {!credential.archived_at ? (
                <>
                  <Button onClick={save} disabled={!dirty || mutationPending}>
                    <Save className="mr-1 h-4 w-4" />
                    {saving ? t('common.loading') : t('common.save')}
                  </Button>
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
          <p className="text-xs text-muted-foreground">{t('managed.table.updated')}</p>
          <p className="mt-1 text-sm">
            <RelativeTime date={credential.updated_at} />
          </p>
        </div>
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">{t('managed.secrets.dataLabel')}</h2>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>
        <div className="space-y-3">
          {pairs.map((pair, index) => (
            <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <Input
                value={pair.key}
                disabled={formReadOnly}
                onChange={(e) => {
                  setPairs((c) =>
                    c.map((it, i) => (i === index ? { ...it, key: e.target.value } : it)),
                  )
                  setDirty(true)
                }}
              />
              <Input
                type={isSecretValueMaskedKey(pair.key) && !showValues ? 'password' : 'text'}
                value={pair.value}
                disabled={formReadOnly}
                onChange={(e) => {
                  setPairs((c) =>
                    c.map((it, i) => (i === index ? { ...it, value: e.target.value } : it)),
                  )
                  setDirty(true)
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={formReadOnly}
                onClick={() => {
                  setPairs((c) => c.filter((_, i) => i !== index))
                  setDirty(true)
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          {!credentialReadOnly ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={formReadOnly}
              onClick={() => {
                setPairs((c) => [...c, { key: '', value: '' }])
                setDirty(true)
              }}
            >
              <Plus className="mr-1 h-4 w-4" />
              {t('managed.secrets.addPair')}
            </Button>
          ) : null}
        </div>
      </section>
      {referencesQuery.data && (
        <CredentialReferences data={referencesQuery.data} variant="informational" />
      )}
      <AlertDialog
        open={Boolean(confirmAction)}
        onOpenChange={(open) => {
          if (open) return
          if (confirmedRef.current) {
            confirmedRef.current = false
            return
          }
          bumpRun()
          setConfirmAction(null)
        }}
      >
        <AlertDialogContent variant={confirmAction === 'delete' ? 'destructive' : 'default'}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t(
                confirmAction === 'delete'
                  ? 'managed.secrets.deleteTitle'
                  : confirmAction === 'restore'
                    ? 'managed.secrets.restoreTitle'
                    : 'managed.secrets.archiveTitle',
              )}
            </AlertDialogTitle>
            <AlertDialogDescription className="whitespace-pre-line leading-relaxed">
              {t(
                confirmAction === 'delete'
                  ? 'managed.secrets.deleteDescription'
                  : confirmAction === 'restore'
                    ? 'managed.secrets.restoreDescription'
                    : 'managed.secrets.archiveDescription',
                { name: credential.name },
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {referencesQuery.data && (
            <CredentialReferences data={referencesQuery.data} variant="blocker" />
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              disabled={mutationPending || blocked}
              onClick={() => {
                confirmedRef.current = true
                confirmLifecycle()
              }}
              className={
                confirmAction === 'delete'
                  ? 'bg-red-600 text-white hover:bg-red-700'
                  : 'bg-foreground text-background hover:opacity-90'
              }
            >
              {t(
                confirmAction === 'delete'
                  ? 'common.delete'
                  : confirmAction === 'restore'
                    ? 'common.restore'
                    : 'common.archive',
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
