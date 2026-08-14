'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { useState } from 'react'

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
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseVaultResponse } from '@/lib/managed/vault-response-parsers'
import type { Vault } from '@/types/managed'

const MAX_NAME_LENGTH = 50

interface CreateVaultDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (vault: Vault) => void
}

interface CreateVaultVariables {
  vaultName: string
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export function CreateVaultDialog({ open, onOpenChange, onCreated }: CreateVaultDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const queryClient = useQueryClient()

  const resetForm = () => {
    setName('')
    mutation.reset()
  }
  const { readOnly, beginAction, isCurrentAction, scopeIsActive, bumpRun } = useScopedActions({
    onReset: () => {
      resetForm()
      onOpenChange(false)
    },
  })

  const mutation = useMutation({
    mutationFn: ({ vaultName, runId, scope, requestScope }: CreateVaultVariables) => {
      if (!isCurrentAction(runId, scope)) throw new Error('Stale vault create ignored')
      return managedPost<unknown>(
        '/credential-groups',
        { name: vaultName },
        managedRequestOptions(requestScope),
      ).then(parseVaultResponse)
    },
    onSuccess: (data, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      onCreated?.(data)
      setName('')
      onOpenChange(false)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'managed.vaults.createFailed')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || trimmed.length > MAX_NAME_LENGTH) return
    const action = beginAction()
    if (!action) {
      resetForm()
      onOpenChange(false)
      return
    }
    mutation.mutate({ vaultName: trimmed, ...action })
  }

  const handleOpenChange = (next: boolean) => {
    if (next && (readOnly || !scopeIsActive())) return
    if (!next) {
      bumpRun()
      resetForm()
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('managed.vaults.createTitle')}</DialogTitle>
          <DialogDescription className="sr-only">
            {t('managed.vaults.createDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {t('managed.vaults.sharedWarning')}{' '}
            <a href="#" className="font-medium underline">
              {t('managed.vaults.learnMore')}
            </a>
            {t('managed.vaults.learnMoreSuffix')}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-2 space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="vault-name" className="text-sm font-medium">
              {t('managed.table.name')}
            </label>
            <Input
              id="vault-name"
              placeholder={t('managed.vaults.namePlaceholder')}
              value={name}
              disabled={readOnly}
              onChange={(e) => setName(e.target.value.slice(0, MAX_NAME_LENGTH))}
              maxLength={MAX_NAME_LENGTH}
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              {t('managed.vaults.nameHint', {
                max: MAX_NAME_LENGTH,
              })}
            </p>
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={!name.trim() || mutation.isPending || readOnly}>
              {mutation.isPending ? t('managed.vaults.creating') : t('common.create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
