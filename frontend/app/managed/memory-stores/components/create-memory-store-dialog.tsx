'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
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
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async () => {
    if (!name.trim()) {
      setError(t('managed.memoryStores.nameRequired'))
      return
    }
    setLoading(true)
    setError('')
    try {
      await managedPost('memory_stores', { name: name.trim(), description: description.trim() })
      setName('')
      setDescription('')
      onOpenChange(false)
      onCreated()
    } catch (e) {
      toastOperationError(t, e, 'managed.memoryStores.createFailed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('managed.memoryStores.createTitle')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div>
            <label className="text-sm font-medium mb-1 block">
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
            <label className="text-sm font-medium mb-1 block">
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
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
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
