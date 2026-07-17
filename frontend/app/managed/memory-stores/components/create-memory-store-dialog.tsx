'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import {
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'

interface CreateMemoryStoreDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}

export function CreateMemoryStoreDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateMemoryStoreDialogProps) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const createRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef(managedScope)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const resetForm = () => {
    setName('')
    setDescription('')
    setError('')
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentCreateRun = (runId: number, scope: string) =>
    runId === createRunRef.current &&
    scope === managedScopeRef.current &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    setLoading(false)
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

  const handleCreate = async () => {
    if (!name.trim()) {
      setError(t('managed.memoryStores.nameRequired'))
      return
    }
    if (!currentProjectAllowsWrite()) {
      resetForm()
      onOpenChange(false)
      return
    }
    const scopeAtStart = managedScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentManagedScopeIsActive(scopeAtStart)) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    setLoading(true)
    setError('')
    try {
      await managedPost(
        'memory_stores',
        { name: name.trim(), description: description.trim() },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentCreateRun(runId, scopeAtStart)) return
      resetForm()
      onOpenChange(false)
      onCreated()
    } catch (e) {
      if (!isCurrentCreateRun(runId, scopeAtStart)) return
      toastOperationError(t, e, 'managed.memoryStores.createFailed')
    } finally {
      if (isCurrentCreateRun(runId, scopeAtStart)) {
        setLoading(false)
      }
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && !currentProjectAllowsWrite()) return
    if (!nextOpen) {
      createRunRef.current += 1
      setLoading(false)
      resetForm()
    }
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('managed.memoryStores.createTitle')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div>
            <label className="mb-1 block text-sm font-medium">
              {t('managed.memoryStores.nameLabel')}
            </label>
            <Input
              placeholder={t('managed.memoryStores.namePlaceholder')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              {t('managed.memoryStores.descriptionLabel')}
            </label>
            <Textarea
              placeholder={t('managed.memoryStores.descriptionPlaceholder')}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="min-h-[80px] resize-y"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleCreate} disabled={loading || !name.trim()}>
            {loading ? '...' : t('common.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
