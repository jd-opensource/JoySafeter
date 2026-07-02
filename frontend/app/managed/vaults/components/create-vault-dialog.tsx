'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import type { Vault } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'

const MAX_NAME_LENGTH = 50

interface CreateVaultDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateVaultDialog({ open, onOpenChange }: CreateVaultDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (vaultName: string) => managedPost<Vault>('/vaults', { name: vaultName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      setName('')
      onOpenChange(false)
    },
    onError: (error) => {
      toastOperationError(t, error, 'managed.vaults.createFailed')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || trimmed.length > MAX_NAME_LENGTH) return
    mutation.mutate(trimmed)
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      mutation.reset()
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
            <Button type="submit" disabled={!name.trim() || mutation.isPending}>
              {mutation.isPending ? t('managed.vaults.creating') : t('common.create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
