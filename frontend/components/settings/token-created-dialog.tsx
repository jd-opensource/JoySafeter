'use client'

import { Check, Copy, X } from 'lucide-react'
import { useState, useCallback } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import type { PlatformTokenCreateResponse } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { formatResourceType } from '@/lib/utils/formatResourceType'

interface TokenCreatedDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  tokenData: PlatformTokenCreateResponse | null
}

export function TokenCreatedDialog({ open, onOpenChange, tokenData }: TokenCreatedDialogProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!tokenData?.token) return
    await navigator.clipboard.writeText(tokenData.token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [tokenData?.token])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl gap-0 overflow-hidden border-0 bg-[#F9F9FA] p-0 shadow-2xl sm:rounded-2xl"
        hideCloseButton
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-elevated)] px-6 py-4">
          <DialogTitle className="text-base font-bold text-[var(--text-primary)]">
            {t('settings.tokens.tokenCreatedTitle')}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t('settings.tokens.tokenCreatedMessage')}
          </DialogDescription>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-full p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="space-y-4 bg-[#F9F9FA] p-6">
          <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-4 py-3 border border-amber-200">
            {t('settings.tokens.tokenCreatedMessage')}
          </p>

          {tokenData && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-[var(--border-muted)]">
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)] w-32">{t('settings.tokens.name')}</td>
                    <td className="px-4 py-3 text-[var(--text-primary)]">{tokenData.name}</td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">Key</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-[var(--text-secondary)] break-all select-all flex-1">
                          {tokenData.token}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={handleCopy}
                          className="h-8 w-8 shrink-0 text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
                        >
                          {copied ? <Check size={15} className="text-emerald-600" /> : <Copy size={15} />}
                        </Button>
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.type')}</td>
                    <td className="px-4 py-3 text-[var(--text-primary)]">{formatResourceType(tokenData.resourceType)}</td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.permissions')}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {tokenData.scopes.map((scope) => (
                          <Badge
                            key={scope}
                            variant="outline"
                            className="rounded-full border-indigo-200 bg-indigo-50 px-2 py-0 text-[10px] font-medium text-indigo-700"
                          >
                            {scope}
                          </Badge>
                        ))}
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.createdAt')}</td>
                    <td className="px-4 py-3 text-[var(--text-primary)]">
                      {tokenData.createdAt
                        ? new Date(tokenData.createdAt).toLocaleString()
                        : '-'}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.expiresAt')}</td>
                    <td className="px-4 py-3 text-[var(--text-primary)]">
                      {tokenData.expiresAt
                        ? new Date(tokenData.expiresAt).toLocaleString()
                        : t('settings.tokens.noExpiry')}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6">
          <Button
            type="button"
            onClick={handleCopy}
            className="gap-2"
            disabled={!tokenData?.token}
          >
            {copied ? (
              <>
                <Check size={16} />
                {t('settings.tokens.copied')}
              </>
            ) : (
              <>
                <Copy size={16} />
                {t('settings.tokens.copyToken')}
              </>
            )}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t('settings.cancel')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
