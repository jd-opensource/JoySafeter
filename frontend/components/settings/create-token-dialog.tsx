'use client'

import { X, Loader2 } from 'lucide-react'
import { useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/i18n'

const AVAILABLE_SCOPES = [
  { value: 'skills:read', label: 'Read' },
  { value: 'skills:write', label: 'Write' },
  { value: 'skills:publish', label: 'Publish' },
  { value: 'skills:admin', label: 'Admin' },
]

interface CreateTokenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (data: { name: string; scopes: string[]; expires_at?: string | null }) => Promise<void>
  isPending: boolean
}

export function CreateTokenDialog({ open, onOpenChange, onSubmit, isPending }: CreateTokenDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [expiresAt, setExpiresAt] = useState('')

  useEffect(() => {
    if (!open) {
      setName('')
      setScopes([])
      setExpiresAt('')
    }
  }, [open])

  const handleScopeToggle = (scope: string) => {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    )
  }

  const handleSubmit = async () => {
    await onSubmit({
      name: name.trim(),
      scopes,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-md gap-0 overflow-hidden border-0 bg-[var(--surface-dialog)] p-0 shadow-2xl sm:rounded-2xl"
        hideCloseButton
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-elevated)] px-6 py-4">
          <DialogTitle className="text-base font-bold text-[var(--text-primary)]">
            {t('settings.tokens.create')}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t('settings.tokens.description')}
          </DialogDescription>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-full p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="space-y-5 bg-[var(--surface-dialog)] p-6">
          {/* Name */}
          <div className="space-y-1.5">
            <Label className="flex items-center gap-1 text-xs font-semibold text-[var(--text-secondary)]">
              <span className="text-red-500">*</span> {t('settings.tokens.name')}
            </Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('settings.tokens.namePlaceholder')}
              className="h-10 border-[var(--border)] bg-[var(--surface-elevated)] text-sm focus-visible:border-primary focus-visible:ring-primary"
            />
          </div>

          {/* Scopes */}
          <div className="space-y-2">
            <Label className="text-xs font-semibold text-[var(--text-secondary)]">
              {t('settings.tokens.scopes')}
            </Label>
            <div className="rounded-xl border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-3 shadow-sm">
              <div className="grid grid-cols-2 gap-3">
                {AVAILABLE_SCOPES.map((scope) => (
                  <div key={scope.value} className="flex items-center gap-2">
                    <Checkbox
                      id={`scope-${scope.value}`}
                      checked={scopes.includes(scope.value)}
                      onCheckedChange={() => handleScopeToggle(scope.value)}
                    />
                    <label
                      htmlFor={`scope-${scope.value}`}
                      className="cursor-pointer text-sm font-medium text-[var(--text-secondary)] select-none"
                    >
                      {scope.label}
                    </label>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Expiration */}
          <div className="space-y-1.5">
            <Label className="text-xs font-semibold text-[var(--text-secondary)]">
              {t('settings.tokens.expiresAt')}
            </Label>
            <Input
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              className="h-10 border-[var(--border)] bg-[var(--surface-elevated)] text-sm focus-visible:border-primary focus-visible:ring-primary"
              placeholder={t('settings.tokens.noExpiry')}
            />
            {!expiresAt && (
              <p className="text-app-xs text-[var(--text-muted)]">{t('settings.tokens.noExpiry')}</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            {t('settings.cancel')}
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={isPending || !name.trim() || scopes.length === 0}
            className="gap-2"
          >
            {isPending && <Loader2 size={16} className="animate-spin" />}
            {t('settings.tokens.create')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
