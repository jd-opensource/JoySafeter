'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { LlmSecretConfigurator } from '@/components/managed/llm/llm-secret-configurator'
import { FormFieldError, FormFieldLabel } from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import { cn } from '@/lib/utils'
import type { SecretDetail } from '@/types/managed'

type CreateSecretKind = 'llm' | 'generic'

interface CreateSecretDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (secret: SecretDetail) => void
  initialKind?: CreateSecretKind
  lockKind?: boolean
}

interface GenericPair {
  key: string
  value: string
}

export function CreateSecretDialog({
  open,
  onOpenChange,
  onCreated,
  initialKind = 'llm',
  lockKind = false,
}: CreateSecretDialogProps) {
  const { t } = useTranslation()
  const [kind, setKind] = useState<CreateSecretKind>(initialKind)
  const [name, setName] = useState('')
  const [pairs, setPairs] = useState<GenericPair[]>([{ key: '', value: '' }])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resetForm = useCallback(() => {
    setKind(initialKind)
    setName('')
    setPairs([{ key: '', value: '' }])
    setSubmitting(false)
    setError(null)
  }, [initialKind])
  const { readOnly, beginAction, isCurrentAction, bumpRun } = useScopedActions({
    onReset: () => {
      resetForm()
      onOpenChange(false)
    },
  })

  useEffect(() => {
    if (!open) return
    resetForm()
  }, [open, resetForm])

  const genericData = useMemo(
    () =>
      Object.fromEntries(
        pairs.map((pair) => [pair.key.trim(), pair.value] as const).filter(([key]) => Boolean(key)),
      ),
    [pairs],
  )

  const createGeneric = async () => {
    if (!name.trim()) {
      setError(t('managed.llm.nameRequired'))
      return
    }
    if (Object.keys(genericData).length === 0) {
      setError(t('managed.llm.genericPairRequired'))
      return
    }
    const action = beginAction()
    if (!action) {
      resetForm()
      onOpenChange(false)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await managedPost<unknown>(
        '/credentials',
        {
          kind: 'service',
          name: name.trim(),
          data: genericData,
          is_default: false,
        },
        managedRequestOptions(action.requestScope),
      )
      if (!isCurrentAction(action.runId, action.scope)) return
      onCreated(parseSecretDetailResponse(response))
      onOpenChange(false)
    } catch (requestError) {
      if (!isCurrentAction(action.runId, action.scope)) return
      setError(requestError instanceof Error ? requestError.message : t('common.operationFailed'))
    } finally {
      if (isCurrentAction(action.runId, action.scope)) setSubmitting(false)
    }
  }

  const handleOpenChange = (next: boolean) => {
    if (next && readOnly) return
    if (!next) {
      bumpRun()
      resetForm()
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t(
              lockKind
                ? kind === 'llm'
                  ? 'managed.credentials.createModelConnection'
                  : 'managed.credentials.createServiceCredential'
                : 'managed.secrets.new',
            )}
          </DialogTitle>
          <DialogDescription>{t('managed.llm.createDialogDescription')}</DialogDescription>
        </DialogHeader>

        {lockKind ? null : (
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-1" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={kind === 'llm'}
              onClick={() => setKind('llm')}
              className={cn(
                'rounded-md px-3 py-2 text-sm font-medium transition-colors',
                kind === 'llm' ? 'bg-background shadow-sm' : 'text-muted-foreground',
              )}
            >
              {t('managed.llm.modelConfiguration')}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={kind === 'generic'}
              onClick={() => setKind('generic')}
              className={cn(
                'rounded-md px-3 py-2 text-sm font-medium transition-colors',
                kind === 'generic' ? 'bg-background shadow-sm' : 'text-muted-foreground',
              )}
            >
              {t('managed.llm.genericSecret')}
            </button>
          </div>
        )}

        {kind === 'llm' ? (
          <LlmSecretConfigurator
            onCreated={(secret) => {
              onCreated(secret)
              handleOpenChange(false)
            }}
            onCancel={() => handleOpenChange(false)}
          />
        ) : (
          <div className="space-y-5">
            <div className="space-y-2">
              <FormFieldLabel htmlFor="generic-secret-name" required>
                {t('managed.llm.configurationName')}
              </FormFieldLabel>
              <Input
                id="generic-secret-name"
                aria-label={t('managed.llm.configurationName')}
                value={name}
                disabled={readOnly}
                onChange={(event) => setName(event.target.value)}
              />
            </div>

            <div className="space-y-3">
              {pairs.map((pair, index) => (
                <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <Input
                    aria-label={t('managed.llm.genericKey')}
                    value={pair.key}
                    disabled={readOnly}
                    placeholder={t('managed.llm.genericKeyPlaceholder')}
                    onChange={(event) =>
                      setPairs((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, key: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  <Input
                    aria-label={t('managed.llm.genericValue')}
                    type="password"
                    autoComplete="new-password"
                    value={pair.value}
                    disabled={readOnly}
                    placeholder={t('managed.llm.genericValuePlaceholder')}
                    onChange={(event) =>
                      setPairs((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, value: event.target.value } : item,
                        ),
                      )
                    }
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={readOnly || pairs.length === 1}
                    onClick={() =>
                      setPairs((current) => current.filter((_, itemIndex) => itemIndex !== index))
                    }
                    aria-label={t('common.delete')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={readOnly}
                onClick={() => setPairs((current) => [...current, { key: '', value: '' }])}
              >
                <Plus className="mr-1 h-4 w-4" />
                {t('managed.secrets.addPair')}
              </Button>
            </div>

            <FormFieldError message={error ?? undefined} />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="button" onClick={createGeneric} disabled={submitting || readOnly}>
                {submitting ? t('common.loading') : t('common.create')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
