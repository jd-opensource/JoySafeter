'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

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
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import { cn } from '@/lib/utils'
import type { SecretDetail } from '@/types/managed'

type CreateSecretKind = 'llm' | 'generic'

interface CreateSecretDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (secret: SecretDetail) => void
  initialKind?: CreateSecretKind
  initialEngineId?: string
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
  initialEngineId,
}: CreateSecretDialogProps) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const [kind, setKind] = useState<CreateSecretKind>(initialKind)
  const [name, setName] = useState('')
  const [pairs, setPairs] = useState<GenericPair[]>([{ key: '', value: '' }])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setKind(initialKind)
    setName('')
    setPairs([{ key: '', value: '' }])
    setSubmitting(false)
    setError(null)
  }, [initialKind, open])

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
    setSubmitting(true)
    setError(null)
    try {
      const response = await managedPost<unknown>(
        '/secrets',
        {
          kind: 'generic',
          name: name.trim(),
          data: genericData,
          is_default: false,
        },
        managedRequestOptions(managedScope),
      )
      onCreated(parseSecretDetailResponse(response))
      onOpenChange(false)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('common.operationFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('managed.secrets.new')}</DialogTitle>
          <DialogDescription>{t('managed.llm.createDialogDescription')}</DialogDescription>
        </DialogHeader>

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

        {kind === 'llm' ? (
          <LlmSecretConfigurator
            initialEngineId={initialEngineId}
            onCreated={(secret) => {
              onCreated(secret)
              onOpenChange(false)
            }}
            onCancel={() => onOpenChange(false)}
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
                onChange={(event) => setName(event.target.value)}
              />
            </div>

            <div className="space-y-3">
              {pairs.map((pair, index) => (
                <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <Input
                    aria-label={t('managed.llm.genericKey')}
                    value={pair.key}
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
                    disabled={pairs.length === 1}
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
                onClick={() => setPairs((current) => [...current, { key: '', value: '' }])}
              >
                <Plus className="mr-1 h-4 w-4" />
                {t('managed.secrets.addPair')}
              </Button>
            </div>

            <FormFieldError message={error ?? undefined} />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="button" onClick={createGeneric} disabled={submitting}>
                {submitting ? t('common.loading') : t('common.create')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
