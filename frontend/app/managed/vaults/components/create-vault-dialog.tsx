'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import {
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
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

interface CreateVaultVariables {
  vaultName: string
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export function CreateVaultDialog({ open, onOpenChange }: CreateVaultDialogProps) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const createRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const [name, setName] = useState('')
  const queryClient = useQueryClient()

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentCreateRun = (runId: number, scope: string) =>
    createRunRef.current === runId &&
    managedScopeRef.current === scope &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const resetForm = () => {
    setName('')
    mutation.reset()
  }

  const mutation = useMutation({
    mutationFn: ({ vaultName, scope, requestScope }: CreateVaultVariables) => {
      if (!currentManagedScopeIsActive(scope)) {
        throw new Error('stale managed scope')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault create ignored')
      }
      return managedPost<Vault>('/vaults', { name: vaultName }, managedRequestOptions(requestScope))
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentCreateRun(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults', scope] })
      setName('')
      onOpenChange(false)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentCreateRun(runId, scope)) return
      toastOperationError(t, error, 'managed.vaults.createFailed')
    },
  })

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    resetForm()
    onOpenChange(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [managedScope.key])

  useEffect(
    () => () => {
      createRunRef.current += 1
    },
    [],
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || trimmed.length > MAX_NAME_LENGTH) return
    if (!currentManagedScopeIsActive()) return
    if (!currentProjectAllowsWrite()) {
      resetForm()
      onOpenChange(false)
      return
    }
    const requestScope = managedRequestScopeRef.current
    const scope = requestScope.key
    if (!currentManagedScopeIsActive(scope)) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    mutation.mutate({ vaultName: trimmed, runId, scope, requestScope })
  }

  const handleOpenChange = (next: boolean) => {
    if (next && !currentProjectAllowsWrite()) return
    if (next && !currentManagedScopeIsActive()) return
    if (!next) {
      createRunRef.current += 1
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
