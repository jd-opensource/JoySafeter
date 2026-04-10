'use client'

import { Loader2 } from 'lucide-react'
import { useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { UnifiedDialog } from '@/components/ui/unified-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/i18n'

const AVAILABLE_SCOPES = [
  { value: 'skills:read', labelKey: 'settings.tokens.scopeRead' },
  { value: 'skills:write', labelKey: 'settings.tokens.scopeWrite' },
  { value: 'skills:publish', labelKey: 'settings.tokens.scopePublish' },
  { value: 'skills:admin', labelKey: 'settings.tokens.scopeAdmin' },
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
    <UnifiedDialog
      open={open}
      onOpenChange={onOpenChange}
      maxWidth="md"
      title={t('settings.tokens.create')}
      description={t('settings.tokens.description')}
      showContentBg={false}
      footer={
        <>
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
        </>
      }
    >
      {/* Name */}
      <div className="space-y-1.5">
        <Label className="flex items-center gap-1 text-xs font-semibold text-[var(--text-secondary)]">
          <span className="text-[var(--status-error)]">*</span> {t('settings.tokens.name')}
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
                  {t(scope.labelKey)}
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
    </UnifiedDialog>
  )
}
