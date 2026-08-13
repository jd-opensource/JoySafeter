'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { MonoId, PageHeader, RelativeTime } from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { isSecretValueMaskedKey } from '@/lib/managed/secret-keys'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { SecretDetail } from '@/types/managed'

interface GenericPair {
  key: string
  value: string
}

export function ServiceCredentialDetail({ credential }: { credential: SecretDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const [pairs, setPairs] = useState<GenericPair[]>(
    Object.entries(credential.data).map(([key, value]) => ({ key, value })),
  )
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (projectReadOnly) return
    const data = Object.fromEntries(
      pairs.map((p) => [p.key.trim(), p.value] as const).filter(([k]) => Boolean(k)),
    )
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data },
        managedRequestOptions(managedScope),
      )
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(['credential-detail', managedScope.key, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
      setPairs(Object.entries(updated.data).map(([key, value]) => ({ key, value })))
      setDirty(false)
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={credential.name}
        breadcrumb={[
          { label: t('managed.credentials.tabs.services'), to: '/managed/credentials?tab=services' },
          { label: credential.name },
        ]}
        titleExtra={<Badge variant="outline">{t('managed.llm.genericSecret')}</Badge>}
        action={
          projectReadOnly ? null : (
            <Button onClick={save} disabled={!dirty || saving}>
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
                disabled={projectReadOnly}
                onChange={(e) => {
                  setPairs((c) => c.map((it, i) => (i === index ? { ...it, key: e.target.value } : it)))
                  setDirty(true)
                }}
              />
              <Input
                type={isSecretValueMaskedKey(pair.key) && !showValues ? 'password' : 'text'}
                value={pair.value}
                disabled={projectReadOnly}
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
                disabled={projectReadOnly}
                onClick={() => {
                  setPairs((c) => c.filter((_, i) => i !== index))
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
    </div>
  )
}
